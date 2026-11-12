"""Retiro de cronogramas: permisos, historial, FK, consultas operativas y refinamiento."""
from __future__ import annotations

import csv
import datetime as dt
import io
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
import time_machine
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.tiempo import hoy_lima
from app.ml.generador import PrediccionDia
from app.ml.historial_bd import construir_historial
from app.models import (Auditoria, Cronograma, CronogramaCiclo, CronogramaEvento, CronogramaTurno,
                        CronogramaVersion, Modulo, NotificacionCorreo, RiegoCiclo, RiegoRegistro, Turno, Usuario)
from app.models.enums import EstadoRiego, OrigenRiego, OrigenVersion, TipoEventoCronograma
from app.repositories import cronogramas as repo
from app.repositories import riego as repo_riego
from app.services import cronograma_service, flujo_cronograma_service as flujo, riego_service
from tests.conftest import API


@pytest.fixture(autouse=True)
def reloj():
    with time_machine.travel(dt.datetime(2026, 11, 11, 15, tzinfo=dt.UTC), tick=False):
        yield


@pytest.fixture
def fabrica(db):
    def crear(fecha=None, numeros=1):
        c = Cronograma(modulo_id=1, fecha=fecha or hoy_lima() - dt.timedelta(days=1))
        db.add(c)
        db.flush()
        versiones = []
        for n in range(1, numeros + 1):
            v = CronogramaVersion(cronograma_id=c.id, numero=n, origen=OrigenVersion.modelo,
                                  basada_en_id=versiones[-1].id if versiones else None)
            db.add(v)
            db.flush()
            for t in repo_riego.turnos_de_modulo(db, 1):
                db.add(CronogramaTurno(version_id=v.id, turno_id=t.id, n_ciclos=1,
                                       n_ciclos_modelo=1, area_ha=t.area_ha, factor_min_por_m3ha=2))
                db.add(CronogramaCiclo(version_id=v.id, turno_id=t.id, ciclo=1, riego_m3ha=20,
                                       riego_m3=20*t.area_ha, duracion_min=40, inicio_min=360,
                                       fin_min=400, hora_inicio="06:00", hora_fin="06:40"))
            db.add(CronogramaEvento(cronograma_id=c.id, version_id=v.id, tipo=TipoEventoCronograma.generado))
            versiones.append(v)
        c.borrador_version_id = versiones[-1].id
        db.commit()
        return c, versiones
    return crear


def borrar(client, cabeceras, crono, **cambios):
    return client.request("DELETE", f"{API}/cronogramas/{crono.id}", headers=cabeceras,
                          json={"motivo": "  Plan reemplazado  ", "lock_version": crono.lock_version, **cambios})


def publicar_visto(client, cabeceras, crono):
    r = client.post(f"{API}/cronogramas/{crono.id}/publicar", headers=cabeceras,
                    json={"lock_version": crono.lock_version})
    assert r.status_code == 200, r.text
    # El Visto ocurrió el día del cronograma; la anulación puede ser retrospectiva.
    with patch.object(flujo, "hoy_lima", return_value=crono.fecha):
        r = client.post(f"{API}/cronogramas/{crono.id}/visto", headers=cabeceras,
                        json={"version_id": r.json()["version_publicada_id"]})
    assert r.status_code == 200, r.text


def test_borrar_borrador_completo_y_auditoria_sobrevive(client, auth, db, fabrica):
    cabeceras = auth("encargado")
    c, vs = fabrica(numeros=2)
    ids = [v.id for v in vs]
    r = borrar(client, cabeceras, c)
    assert r.status_code == 200, r.text
    assert r.json() == {"accion": "eliminado", "cronograma_id": c.id,
                        "fecha": c.fecha.isoformat(), "avisos": []}
    for clase, condicion in (
        (Cronograma, Cronograma.id == c.id), (CronogramaVersion, CronogramaVersion.cronograma_id == c.id),
        (CronogramaEvento, CronogramaEvento.cronograma_id == c.id),
        (CronogramaTurno, CronogramaTurno.version_id.in_(ids)), (CronogramaCiclo, CronogramaCiclo.version_id.in_(ids)),
    ):
        assert db.scalar(select(func.count()).select_from(clase).where(condicion)) == 0
    a = db.scalar(select(Auditoria).where(Auditoria.accion == "eliminar_cronograma", Auditoria.entidad_id == str(c.id)))
    assert a.detalle == {"modulo_id": 1, "modulo": "EN01-MOD5", "fecha": c.fecha.isoformat(),
                         "motivo": "Plan reemplazado", "versiones": [1, 2]}
    assert borrar(client, cabeceras, c).status_code == 404


@pytest.mark.parametrize("rol", ["programador", "subgerente"])
def test_eliminar_solo_editores(client, auth, fabrica, rol):
    c, _ = fabrica()
    assert borrar(client, auth(rol), c).status_code == 403


def test_lock_obsoleto(client, auth, db, fabrica):
    c, _ = fabrica()
    cabeceras = auth()
    assert borrar(client, cabeceras, c, lock_version=c.lock_version + 1).status_code == 409
    assert repo.obtener(db, c.id) is not None


@pytest.mark.parametrize("cambio", [{"motivo": "  ab  "}, {"motivo": "x"*501}, {"motivo": "   "},
                                   {"lock_version": True}, {"lock_version": 1.5}])
def test_validar_entrada(client, auth, fabrica, cambio):
    c, _ = fabrica()
    assert borrar(client, auth(), c, **cambio).status_code == 422


def test_anular_visto_retira_solo_provisionales_propios(client, auth, db, fabrica):
    cabeceras = auth()
    actor = db.scalar(select(Usuario).where(Usuario.username == "admin_prueba"))
    c, vs = fabrica(numeros=2)
    publicar_visto(client, cabeceras, c)
    otro, otras = fabrica(fecha=c.fecha - dt.timedelta(days=1))
    turnos = repo_riego.turnos_de_modulo(db, 1)
    originales = {r.turno_id: r for r in repo_riego.vigentes(db, 1)}
    # Aplicado, manual, Excel y otro cronograma se conservan. TE05 sí se retira.
    for turno, estado, origen, version in (
        (turnos[0], EstadoRiego.aplicado, OrigenRiego.cronograma, vs[-1].id),
        (turnos[1], EstadoRiego.provisional, OrigenRiego.manual, None),
        (turnos[2], EstadoRiego.provisional, OrigenRiego.excel, None),
        (turnos[3], EstadoRiego.provisional, OrigenRiego.cronograma, otras[0].id),
    ):
        riego_service._crear_registro(db, turno=turno, fecha=c.fecha, vigente=originales[turno.id],
                                      ciclos=[], sin_riego=True, estado=estado, origen=origen,
                                      cronograma_version_id=version, actor=actor)
    retirado = originales[turnos[4].id]
    hash_original, version_original = retirado.contenido_sha256, retirado.version
    db.commit()
    r = borrar(client, cabeceras, c)
    assert r.status_code == 200, r.text
    assert r.json()["accion"] == "anulado"
    assert r.json()["avisos"] == ["TE01: riego aplicado; se conservó",
        "TE02: riego provisional manual; se conservó", "TE03: riego provisional de otro origen; se conservó",
        "TE04: riego provisional de otro cronograma; se conservó"]
    db.refresh(c)
    db.refresh(retirado)
    assert c.anulado_por == actor.id and c.anulado_at and c.anulado_motivo == "Plan reemplazado"
    assert not retirado.vigente
    assert (retirado.contenido_sha256, retirado.version) == (hash_original, version_original)
    assert db.scalar(select(func.count()).select_from(RiegoCiclo).where(RiegoCiclo.registro_id == retirado.id)) == 1
    evento = db.scalar(select(CronogramaEvento).where(CronogramaEvento.cronograma_id == c.id,
                                                     CronogramaEvento.tipo == TipoEventoCronograma.anulado))
    assert evento.comentario == "Plan reemplazado" and evento.detalle["registros_retirados"] == [retirado.id]
    assert db.scalar(select(Auditoria.id).where(Auditoria.accion == "anular_cronograma", Auditoria.entidad_id == str(c.id)))
    listado = client.get(f"{API}/riego", headers=cabeceras,
                        params={"modulo_id": 1, "desde": str(c.fecha), "hasta": str(c.fecha)}).json()["registros"]
    assert {r["turno_codigo"] for r in listado} == {"TE01", "TE02", "TE03", "TE04"}
    # El próximo registro usa max(version)+1, sin reactivar versiones antiguas ni colisionar.
    nuevo = riego_service._crear_registro(db, turno=turnos[4], fecha=c.fecha, vigente=None, ciclos=[],
                                          sin_riego=True, estado=EstadoRiego.provisional,
                                          origen=OrigenRiego.manual, actor=actor)
    assert nuevo.version == version_original + 1


def test_anulado_fuera_de_operacion_y_presente_en_csv(client, auth, db, fabrica):
    cabeceras = auth()
    c, _ = fabrica()
    publicar_visto(client, cabeceras, c)
    assert borrar(client, cabeceras, c).json()["accion"] == "anulado"
    params = {"modulo_id": 1, "desde": str(c.fecha), "hasta": str(c.fecha)}
    assert client.get(f"{API}/cronogramas", headers=cabeceras, params=params).json() == []
    assert client.get(f"{API}/cronogramas/por-fecha", headers=cabeceras,
                      params={"modulo_id": 1, "fecha": str(c.fecha)}).json() is None
    for ruta in ("", "/versiones", "/versiones/1", "/eventos", "/alternativas", "/datos-campo", "/exportar"):
        assert client.get(f"{API}/cronogramas/{c.id}{ruta}", headers=cabeceras).status_code == 404
    for ruta, datos in (("publicar", {"lock_version": c.lock_version}), ("regenerar", {}),
                        ("visto", {"version_id": c.version_publicada_id}),
                        ("mantener", {"comentario": "Conservar el plan"})):
        assert client.post(f"{API}/cronogramas/{c.id}/{ruta}", headers=cabeceras, json=datos).status_code == 404
    agua = client.get(f"{API}/datos/agua", headers=cabeceras, params=params).json()["dias"][0]
    assert agua["cronograma_id"] is None
    assert all(t["propuesto_m3"] is None and t["modelo_m3"] is None and t["estado_riego"] is None for t in agua["turnos"])
    assert repo.bloquear_rango(db, 1, [c.fecha]) == {}
    assert repo_riego.ciclos_cronograma_referencia(db, 1, hoy_lima()) == []
    assert construir_historial(db, 1, hasta=hoy_lima()).turno_dias_cronograma == []
    frescura = client.get(f"{API}/datos/frescura", headers=cabeceras, params={"modulo_id": 1}).json()
    provisional = next(f for f in frescura["fuentes"] if f["fuente"] == "riego_provisional")
    assert provisional["ultima_fecha"] is None
    assert all(t["ultima_fecha"] is None for t in provisional["por_turno"])
    dash = client.get(f"{API}/dashboard", headers=cabeceras, params={"modulo_id": 1}).json()
    assert dash["ultimo_riego_fecha"] is None and dash["agua_aplicada_m3"] is None
    # Misma fecha activa y anulada: el CSV incluye ambas sin colapsarlas por fecha.
    fabrica(fecha=c.fecha)
    csv_res = client.get(f"{API}/exportaciones/refinamiento.csv", headers=cabeceras,
                         params={"desde": str(c.fecha), "hasta": str(c.fecha)})
    lector = csv.DictReader(io.StringIO(csv_res.content.decode("utf-8-sig")))
    assert lector.fieldnames[-2:] == ["anulado", "anulado_motivo"]
    filas = list(lector)
    assert {f["anulado"] for f in filas} == {"True", "False"}
    assert len([f for f in filas if f["anulado"] == "True" and f["anulado_motivo"] == "Plan reemplazado"]) == 5


@pytest.mark.parametrize("referencia", ["correo", "riego_no_vigente", "version_ajena", "puntero_ajeno", "evento_ajeno"])
def test_borrador_con_referencia_externa_se_anula(client, auth, db, fabrica, referencia):
    cabeceras = auth()
    c, vs = fabrica()
    if referencia == "correo":
        db.add(NotificacionCorreo(cronograma_id=c.id, tipo="cronograma_publicado", asunto="Prueba"))
    elif referencia == "riego_no_vigente":
        db.add(RiegoRegistro(modulo_id=1, turno_id=1, fecha=c.fecha, version=1, vigente=False,
                             estado=EstadoRiego.provisional, origen=OrigenRiego.cronograma, sin_riego=True,
                             contenido_sha256="0"*64, cronograma_version_id=vs[0].id))
    else:
        otro, _ = fabrica(fecha=c.fecha - dt.timedelta(days=1))
        if referencia == "version_ajena":
            db.add(CronogramaVersion(cronograma_id=otro.id, numero=2, origen=OrigenVersion.edicion,
                                      basada_en_id=vs[0].id))
        elif referencia == "puntero_ajeno":
            otro.borrador_version_id = vs[0].id
        else:
            db.add(CronogramaEvento(cronograma_id=otro.id, version_id=vs[0].id, tipo=TipoEventoCronograma.generado))
    db.commit()
    assert borrar(client, cabeceras, c).json()["accion"] == "anulado"
    assert db.scalar(select(CronogramaVersion.id).where(CronogramaVersion.id == vs[0].id))


def test_generar_tras_anular_crea_otro_cronograma(client, auth, db, fabrica, monkeypatch):
    cabeceras = auth()
    c, _ = fabrica()
    publicar_visto(client, cabeceras, c)
    assert borrar(client, cabeceras, c).json()["accion"] == "anulado"
    # Sustituye solo las fronteras del modelo; persiste y decide con la implementación real.
    monkeypatch.setattr(repo, "dias_con_riego_antes", lambda *a: 45)
    modelo = SimpleNamespace(plan=object(), version="prueba")
    monkeypatch.setattr(cronograma_service, "cargar_modelo", lambda: modelo)
    monkeypatch.setattr(cronograma_service, "registrar_version", lambda *a: None)
    prediccion = PrediccionDia(c.fecha, pd.DataFrame([{
        "Turno": "TE01", "n_ciclos": 1, "Ciclo": 1, "riego_m3ha": 20., "riego_m3": 260.38,
        "duracion_min": 40., "inicio_min": 360., "fin_min": 400., "hora_inicio": "06:00", "hora_fin": "06:40", "fin_dia_siguiente": False,
    }]), {}, {})
    monkeypatch.setattr(cronograma_service.generador, "predecir_dia", lambda *a: prediccion)
    monkeypatch.setattr(cronograma_service.generador, "agregar", lambda historial, pred: historial)
    r = client.post(f"{API}/cronogramas/generar", headers=cabeceras,
                    json={"modulo_id": 1, "fecha_inicio": str(c.fecha), "dias": 1})
    assert r.status_code == 200, r.text
    creado = r.json()["dias_resultado"][0]
    assert creado["accion"] == "creado" and creado["cronograma_id"] != c.id and creado["version"] == 1
    assert repo.por_fecha(db, 1, c.fecha).id == creado["cronograma_id"]


def test_dashboard_excluye_cronograma_anulado_de_manana(client, auth, db, fabrica):
    cabeceras = auth()
    c, _ = fabrica(fecha=hoy_lima() + dt.timedelta(days=1))
    publicar_visto(client, cabeceras, c)
    assert borrar(client, cabeceras, c).status_code == 200
    r = client.get(f"{API}/dashboard", headers=cabeceras, params={"modulo_id": 1})
    assert r.json()["cronograma_manana_id"] is None and r.json()["estado_manana"] is None


@pytest.mark.parametrize("estado", [EstadoRiego.aplicado, EstadoRiego.provisional])
def test_dashboard_ultimo_riego_vigente_hasta_ayer(client, auth, db, estado):
    cabeceras = auth()
    params = {"modulo_id": 1}
    assert client.get(f"{API}/dashboard", headers=cabeceras, params=params).json()["ultimo_riego_fecha"] is None
    for dias, turno, vigente in ((5, 1, True), (2, 2, True), (1, 3, False), (0, 4, True), (-1, 5, True)):
        db.add(RiegoRegistro(modulo_id=1, turno_id=turno, fecha=hoy_lima() - dt.timedelta(days=dias),
                             version=1, vigente=vigente, estado=estado, origen=OrigenRiego.manual,
                             sin_riego=True, contenido_sha256="0"*64))
    # Un módulo diferente con fecha más reciente no afecta al elegido.
    otro = Modulo(fundo_id=1, codigo="OTRO", nombre="Otro módulo", area_ha=1)
    db.add(otro)
    db.flush()
    turno_otro = Turno(modulo_id=otro.id, codigo="OT01", orden=1, area_ha=1, valvula_controlador="prueba-otra")
    db.add(turno_otro)
    db.flush()
    db.add(RiegoRegistro(modulo_id=otro.id, turno_id=turno_otro.id, fecha=hoy_lima()-dt.timedelta(days=1),
                         version=1, estado=estado, origen=OrigenRiego.manual, sin_riego=True, contenido_sha256="0"*64))
    db.commit()
    r = client.get(f"{API}/dashboard", headers=cabeceras, params=params)
    assert r.status_code == 200, r.text
    assert r.json()["ultimo_riego_fecha"] == str(hoy_lima() - dt.timedelta(days=2))


def test_bd_no_permite_borrar_publicados_ni_dependencias_sueltas(db, fabrica, crear_usuario):
    actor = crear_usuario("editor")
    c, vs = fabrica()
    for clase, filtro in ((CronogramaVersion, CronogramaVersion.id == vs[0].id),
                          (CronogramaCiclo, CronogramaCiclo.version_id == vs[0].id),
                          (CronogramaTurno, CronogramaTurno.version_id == vs[0].id),
                          (CronogramaEvento, CronogramaEvento.cronograma_id == c.id)):
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(delete(clase).where(filtro))
    flujo.publicar(db, c.id, c.lock_version, actor)
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(delete(Cronograma).where(Cronograma.id == c.id))


def test_fk_no_mapeada_en_orm_tambien_impide_borrado(conexion):
    # Una futura tabla con FK (incluso ON DELETE CASCADE) debe provocar anulación,
    # no la eliminación silenciosa de datos externos al árbol del cronograma.
    from sqlalchemy.orm import Session
    with Session(bind=conexion, join_transaction_mode="create_savepoint") as sesion:
        c = Cronograma(modulo_id=1, fecha=hoy_lima())
        sesion.add(c)
        sesion.flush()
        conexion.exec_driver_sql("CREATE TABLE riego.referencia_prueba (id bigint PRIMARY KEY, "
                                 "cronograma_id bigint REFERENCES riego.cronograma(id) ON DELETE CASCADE)")
        conexion.execute(text("INSERT INTO riego.referencia_prueba VALUES (1, :id)"), {"id": c.id})
        assert repo.tiene_referencias_externas(sesion, c.id)


def test_anulacion_y_retiro_se_deshacen_juntos(db, fabrica, crear_usuario):
    actor = crear_usuario("transaccion")
    c, vs = fabrica()
    flujo.publicar(db, c.id, c.lock_version, actor)
    with patch.object(flujo, "hoy_lima", return_value=c.fecha):
        flujo.visto(db, c.id, vs[0].id, actor)
    db.commit()
    with pytest.raises(RuntimeError), db.begin_nested():
        flujo.eliminar(db, c.id, "Prueba de rollback", c.lock_version, actor)
        raise RuntimeError("Fallo antes del commit")
    db.refresh(c)
    assert c.anulado_at is None
    assert len(repo_riego.vigentes(db, c.modulo_id)) == 5
    assert not db.scalar(select(Auditoria.id).where(Auditoria.accion == "anular_cronograma",
                                                   Auditoria.entidad_id == str(c.id)))
