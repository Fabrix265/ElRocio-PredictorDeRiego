"""Riego aplicado y carga de Excel (§3.5, §4 "Riego aplicado", decisión D7).

Cubre permisos por rol en cada endpoint, el flujo subir → vista previa → marcar → confirmar →
resubir (todo "igual"), los resultados de la comparación, el vencimiento (24 h o registro
comparado cambiado), la auditoría y la validación del archivo (incluidos archivos maliciosos).
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tiempo import ahora_utc, hoy_lima
from app.models import Auditoria, CargaRiego, Modulo, RiegoRegistro, Turno
from app.models.enums import EstadoRiego, OrigenRiego
from app.repositories import riego as repo
from app.services import archivo_excel, carga_riego_service
from app.services.riego_contenido import hash_contenido
from tests.conftest import API

CABECERA = ["fecha", "Fundo", "Modulo", "Turno", "Valvula", "Hora Inicio", "Hora Fin",
            "Tiempo de riego (minutos)", "Cantidad de riego (m3)", "Cantidad de riego (m3 por hectarea)"]
VALVULAS = {"TE01": 6061000, "TE02": 6263000, "TE03": 6465000, "TE04": 6667000, "TE05": 6869000}
AREAS = {"TE01": 13.019, "TE02": 12.649, "TE03": 12.423, "TE04": 12.459, "TE05": 12.2792}
D1 = dt.date(2026, 10, 1)
D2 = dt.date(2026, 10, 2)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def fila(fecha: dt.date, turno: str, inicio: str, minutos: float, m3: float, *,
         fundo: str = "ENSUEÑO 1", modulo: str = "EN01-MOD5", valvula: int | None = None) -> list:
    h, m = (int(x) for x in inicio.split(":"))
    fin = (dt.datetime.combine(fecha, dt.time(h, m)) + timedelta(minutes=minutos)).time()
    return [dt.datetime.combine(fecha, dt.time()), fundo, modulo, turno,
            valvula if valvula is not None else VALVULAS.get(turno, 9999999),
            dt.time(h, m), fin, minutos, m3, m3 / AREAS.get(turno, 12.5)]


def excel(filas: list[list], *, hoja: str = "MOD5", cabecera: list[str] = CABECERA) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = hoja
    ws.append(cabecera)
    for f in filas:
        ws.append(f)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def filas_base() -> list[list]:
    """D1: TE01 (2 ciclos) y TE02; TE03–TE05 sin filas (D7). D2: TE01–TE04 y TE05 solo con una
    apertura fallida (2 min)."""
    return [
        fila(D1, "TE01", "06:00", 60, 200), fila(D1, "TE01", "14:00", 45, 150),
        fila(D1, "TE02", "07:00", 60, 190),
        *[fila(D2, t, "08:00", 50, 170) for t in ("TE01", "TE02", "TE03", "TE04")],
        fila(D2, "TE05", "09:00", 2, 30),
    ]


@pytest.fixture
def modulo_id(db: Session) -> int:
    return db.scalars(select(Modulo.id).where(Modulo.codigo == "EN01-MOD5")).one()


@pytest.fixture
def turnos(db: Session, modulo_id: int) -> dict[str, int]:
    return {t.codigo: t.id for t in db.scalars(select(Turno).where(Turno.modulo_id == modulo_id))}


def subir(client: TestClient, cabeceras: dict, modulo_id: int, contenido: bytes,
          nombre: str = "riego MOD5.xlsx"):
    return client.post(f"{API}/riego/cargas", headers=cabeceras,
                       files={"archivo": (nombre, contenido, XLSX)}, data={"modulo_id": str(modulo_id)})


def grupo(carga: dict, fecha: dt.date, turno: str) -> dict:
    return next(g for g in carga["grupos"] if g["fecha"] == fecha.isoformat() and g["turno_codigo"] == turno)


def crear_registro(db: Session, modulo_id: int, turno_id: int, fecha: dt.date, *, estado: EstadoRiego,
                   origen: OrigenRiego, ciclos: list[dict] | None = None) -> int:
    ciclos = ciclos if ciclos is not None else [{
        "inicio_min": 300.0, "fin_min": 340.0, "duracion_min": 40.0, "riego_m3": 100.0,
        "riego_m3ha": 8.0, "area_ha": 12.5, "valvula": "6061000", "hora_inicio": "05:00",
        "hora_fin": "05:40", "fin_dia_siguiente": False,
    }]
    ids = repo.insertar_registros(db, [{
        "modulo_id": modulo_id, "turno_id": turno_id, "fecha": fecha, "version": 1, "vigente": True,
        "estado": estado, "origen": origen, "sin_riego": False,
        "contenido_sha256": hash_contenido(ciclos), "motivo": "prueba",
    }])
    repo.insertar_ciclos(db, [{"registro_id": ids[(turno_id, fecha)], **c} for c in ciclos])
    db.commit()
    return ids[(turno_id, fecha)]


def acciones(db: Session, carga_id: int) -> list[str]:
    return list(db.scalars(
        select(Auditoria.accion).where(Auditoria.entidad == "carga_riego",
                                       Auditoria.entidad_id == str(carga_id)).order_by(Auditoria.id)
    ))


# --- Permisos por rol -------------------------------------------------------------

@pytest.mark.parametrize("rol", ["admin", "encargado", "subgerente", "programador"])
def test_listado_de_riego_para_todos(client: TestClient, auth, modulo_id: int, rol: str):
    respuesta = client.get(f"{API}/riego", headers=auth(rol), params={"modulo_id": modulo_id})
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["modulo_id"] == modulo_id and cuerpo["registros"] == []
    assert cuerpo["hasta"] == hoy_lima().isoformat()


@pytest.mark.parametrize(("rol", "esperado"), [
    ("admin", 200), ("encargado", 200), ("subgerente", 200), ("programador", 403),
])
def test_versiones_permisos(client: TestClient, auth, turnos, rol: str, esperado: int):
    respuesta = client.get(f"{API}/riego/{turnos['TE01']}/{D1}/versiones", headers=auth(rol))
    assert respuesta.status_code == esperado, respuesta.text


@pytest.mark.parametrize("rol", ["subgerente", "programador"])
def test_cargas_solo_admin_y_encargado(client: TestClient, auth, modulo_id: int, rol: str):
    cabeceras = auth(rol)
    assert subir(client, cabeceras, modulo_id, excel(filas_base())).status_code == 403
    assert client.get(f"{API}/riego/cargas/1", headers=cabeceras).status_code == 403
    assert client.patch(f"{API}/riego/cargas/1", headers=cabeceras,
                        json={"grupos": [{"id": 1, "aplicar": False}]}).status_code == 403
    assert client.post(f"{API}/riego/cargas/1/confirmar", headers=cabeceras).status_code == 403
    assert client.post(f"{API}/riego/cargas/1/descartar", headers=cabeceras).status_code == 403


def test_riego_sin_sesion_401(client: TestClient, modulo_id: int, turnos):
    assert client.get(f"{API}/riego", params={"modulo_id": modulo_id}).status_code == 401
    assert client.get(f"{API}/riego/{turnos['TE01']}/{D1}/versiones").status_code == 401
    assert subir(client, {}, modulo_id, excel(filas_base())).status_code == 401
    assert client.get(f"{API}/riego/cargas/1").status_code == 401


def test_listado_valida_parametros(client: TestClient, auth, modulo_id: int):
    cabeceras = auth("programador")
    assert client.get(f"{API}/riego", headers=cabeceras).status_code == 422
    assert client.get(f"{API}/riego", headers=cabeceras, params={"modulo_id": 999999}).status_code == 404
    assert client.get(f"{API}/riego", headers=cabeceras, params={
        "modulo_id": modulo_id, "desde": "2026-10-05", "hasta": "2026-10-01"}).status_code == 422
    assert client.get(f"{API}/riego", headers=cabeceras, params={
        "modulo_id": modulo_id, "desde": "2024-01-01", "hasta": "2026-10-01"}).status_code == 422


@pytest.mark.parametrize("rol", ["admin", "encargado"])
def test_carga_inexistente_404(client: TestClient, auth, rol: str):
    cabeceras = auth(rol)
    assert client.get(f"{API}/riego/cargas/999999", headers=cabeceras).status_code == 404
    assert client.post(f"{API}/riego/cargas/999999/confirmar", headers=cabeceras).status_code == 404


# --- Flujo completo -------------------------------------------------------------

def test_flujo_subir_marcar_confirmar_y_resubir(client: TestClient, auth, db: Session, modulo_id, turnos):
    cabeceras = auth("encargado")
    respuesta = subir(client, cabeceras, modulo_id, excel(filas_base()), nombre="../carpeta/riego MOD5.xlsx")
    assert respuesta.status_code == 201, respuesta.text
    carga = respuesta.json()
    assert carga["estado"] == "previsualizada" and carga["subido_por"] == "encargado_prueba"
    assert carga["archivo_nombre"] == "riego MOD5.xlsx"  # sin carpetas
    assert carga["resumen"]["contadores"] == {
        "nuevo": 6, "igual": 0, "reemplaza_provisional": 0, "reemplaza_aplicado": 0,
        "sin_riego": 4, "error": 0,
    }
    assert carga["resumen"]["desde"] == D1.isoformat() and carga["resumen"]["hasta"] == D2.isoformat()
    te01 = grupo(carga, D1, "TE01")
    assert te01["resultado"] == "nuevo" and te01["aplicar"] is True
    assert [c["hora_inicio"] for c in te01["ciclos"]] == ["06:00", "14:00"]
    d7 = grupo(carga, D1, "TE03")
    assert d7["resultado"] == "sin_riego" and d7["aplicar"] is True and d7["ciclos"] == []
    assert "D7" in d7["mensajes"][0]
    fallida = grupo(carga, D2, "TE05")
    assert fallida["resultado"] == "sin_riego" and "aperturas fallidas" in fallida["mensajes"][0]
    assert acciones(db, carga["id"]) == ["excel_subido"]

    # GET devuelve lo mismo; PATCH desmarca un "sin riego" (D7).
    assert client.get(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras).json() == carga
    respuesta = client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras,
                             json={"grupos": [{"id": d7["id"], "aplicar": False}]})
    assert respuesta.status_code == 200, respuesta.text
    assert grupo(respuesta.json(), D1, "TE03")["aplicar"] is False

    respuesta = client.post(f"{API}/riego/cargas/{carga['id']}/confirmar", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    confirmada = respuesta.json()
    assert confirmada["estado"] == "confirmada" and confirmada["confirmado_por"] == "encargado_prueba"
    assert confirmada["resumen"]["registros_creados"] == 9
    assert acciones(db, carga["id"]) == ["excel_subido", "excel_confirmado"]

    listado = client.get(f"{API}/riego", headers=auth("programador"), params={
        "modulo_id": modulo_id, "desde": D1.isoformat(), "hasta": D2.isoformat()}).json()
    registros = {(r["fecha"], r["turno_codigo"]): r for r in listado["registros"]}
    assert len(registros) == 9 and (D1.isoformat(), "TE03") not in registros
    r = registros[(D1.isoformat(), "TE01")]
    assert (r["estado"], r["origen"], r["sin_riego"], r["version"]) == ("aplicado", "excel", False, 1)
    assert r["carga_id"] == carga["id"] and len(r["ciclos"]) == 2 and r["creado_por"] == "encargado_prueba"
    assert registros[(D1.isoformat(), "TE04")]["sin_riego"] is True
    assert registros[(D1.isoformat(), "TE04")]["ciclos"] == []

    # Confirmar otra vez: 409. Resubir el mismo archivo: todo "igual" salvo el desmarcado.
    assert client.post(f"{API}/riego/cargas/{carga['id']}/confirmar", headers=cabeceras).status_code == 409
    segunda = subir(client, cabeceras, modulo_id, excel(filas_base())).json()
    assert segunda["resumen"]["contadores"]["igual"] == 9
    assert segunda["resumen"]["contadores"]["sin_riego"] == 1
    assert grupo(segunda, D1, "TE01")["aplicar"] is False
    respuesta = client.post(f"{API}/riego/cargas/{segunda['id']}/descartar", headers=cabeceras)
    assert respuesta.status_code == 200 and respuesta.json()["estado"] == "descartada"
    # Descartar otra vez no cambia nada; confirmar una descartada: 409.
    assert client.post(f"{API}/riego/cargas/{segunda['id']}/descartar", headers=cabeceras).status_code == 200
    assert client.post(f"{API}/riego/cargas/{segunda['id']}/confirmar", headers=cabeceras).status_code == 409
    assert acciones(db, segunda["id"]) == ["excel_subido", "excel_descartado"]


def test_reemplazos_y_versiones(client: TestClient, auth, db: Session, modulo_id, turnos):
    prov = crear_registro(db, modulo_id, turnos["TE01"], D1, estado=EstadoRiego.provisional,
                          origen=OrigenRiego.cronograma)
    manual = crear_registro(db, modulo_id, turnos["TE02"], D1, estado=EstadoRiego.aplicado,
                            origen=OrigenRiego.manual)
    hist = crear_registro(db, modulo_id, turnos["TE01"], D2, estado=EstadoRiego.aplicado,
                          origen=OrigenRiego.historico)
    aplicado_d7 = crear_registro(db, modulo_id, turnos["TE03"], D1, estado=EstadoRiego.aplicado,
                                 origen=OrigenRiego.historico)
    cabeceras = auth("admin")
    carga = subir(client, cabeceras, modulo_id, excel(filas_base())).json()
    assert carga["resumen"]["contadores"] == {
        "nuevo": 3, "igual": 0, "reemplaza_provisional": 1, "reemplaza_aplicado": 2,
        "sin_riego": 4, "error": 0,
    }
    g_prov = grupo(carga, D1, "TE01")
    assert (g_prov["resultado"], g_prov["aplicar"], g_prov["vigente_id_comparado"]) == (
        "reemplaza_provisional", True, prov)
    assert (g_prov["vigente_estado"], g_prov["vigente_origen"]) == ("provisional", "cronograma")
    # El vigente manual queda desmarcado por defecto; el histórico, marcado.
    assert (grupo(carga, D1, "TE02")["resultado"], grupo(carga, D1, "TE02")["aplicar"]) == (
        "reemplaza_aplicado", False)
    assert (grupo(carga, D2, "TE01")["resultado"], grupo(carga, D2, "TE01")["aplicar"]) == (
        "reemplaza_aplicado", True)
    # D7 sobre un aplicado: se muestra, pero desmarcado.
    g_d7 = grupo(carga, D1, "TE03")
    assert (g_d7["resultado"], g_d7["aplicar"], g_d7["vigente_id_comparado"]) == ("sin_riego", False, aplicado_d7)

    # Se marca el manual y se confirma.
    client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras,
                 json={"grupos": [{"id": grupo(carga, D1, "TE02")["id"], "aplicar": True}]})
    respuesta = client.post(f"{API}/riego/cargas/{carga['id']}/confirmar", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resumen"]["registros_creados"] == 9

    versiones = client.get(f"{API}/riego/{turnos['TE02']}/{D1}/versiones", headers=auth("subgerente")).json()
    assert [(v["version"], v["vigente"], v["origen"], v["estado"]) for v in versiones] == [
        (1, False, "manual", "aplicado"), (2, True, "excel", "aplicado")]
    assert versiones[1]["basado_en_id"] == manual and versiones[1]["motivo"] == "Carga de Excel"
    assert len(versiones[0]["ciclos"]) == 1  # el original se conserva con sus ciclos
    assert db.get(RiegoRegistro, hist).vigente is False
    assert db.get(RiegoRegistro, aplicado_d7).vigente is True  # desmarcado: no se toca


def test_errores_en_la_vista_previa(client: TestClient, auth, modulo_id):
    hoy = hoy_lima()
    filas = [
        fila(D1, "TE09", "06:00", 60, 200),                        # turno desconocido
        fila(D1, "TE02", "06:00", 60, 200, valvula=1234567),       # válvula de otro turno
        fila(hoy, "TE01", "06:00", 60, 200),                       # fecha de hoy
        fila(D2, "TE03", "06:00", 60, 200), fila(D2, "TE03", "06:00", 40, 120),  # inicio repetido
        fila(D2, "TE04", "06:00", 60, 200), fila(D2, "TE04", "06:00", 60, 200),  # duplicado exacto
        fila(D2, "TE01", "06:00", 60, 200, modulo="EN01-MOD9"),    # otro módulo
    ]
    cabeceras = auth("admin")
    respuesta = subir(client, cabeceras, modulo_id, excel(filas))
    assert respuesta.status_code == 201, respuesta.text
    carga = respuesta.json()
    errores = {(g["fecha"], g["turno_codigo"]): g["mensajes"] for g in carga["grupos"] if g["resultado"] == "error"}
    assert "desconocido" in errores[(D1.isoformat(), "TE09")][0]
    assert "Válvula 1234567" in errores[(D1.isoformat(), "TE02")][0]
    assert "hoy o futura" in errores[(hoy.isoformat(), "TE01")][0]
    assert "repetido con valores distintos" in errores[(D2.isoformat(), "TE03")][0]
    assert "otro fundo o módulo" in errores[(D2.isoformat(), "TE01")][0]
    assert all(not g["aplicar"] for g in carga["grupos"] if g["resultado"] == "error")
    # El duplicado exacto no es error: limpiar_ciclos lo quita.
    te04 = grupo(carga, D2, "TE04")
    assert te04["resultado"] == "nuevo" and len(te04["ciclos"]) == 1

    # Los grupos con error no se pueden marcar.
    error_id = next(g["id"] for g in carga["grupos"] if g["resultado"] == "error")
    assert client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras,
                        json={"grupos": [{"id": error_id, "aplicar": True}]}).status_code == 422
    # Grupo de otra carga o inexistente: 422. Cuerpo vacío o con campos extra: 422.
    assert client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras,
                        json={"grupos": [{"id": 999999999, "aplicar": True}]}).status_code == 422
    assert client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras,
                        json={"grupos": []}).status_code == 422
    assert client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras,
                        json={"grupos": [{"id": error_id, "aplicar": True, "x": 1}]}).status_code == 422


def test_confirmar_sin_nada_marcado_422(client: TestClient, auth, modulo_id):
    cabeceras = auth("admin")
    carga = subir(client, cabeceras, modulo_id, excel([fila(D1, "TE01", "06:00", 60, 200)])).json()
    marcados = [{"id": g["id"], "aplicar": False} for g in carga["grupos"] if g["aplicar"]]
    client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras, json={"grupos": marcados})
    respuesta = client.post(f"{API}/riego/cargas/{carga['id']}/confirmar", headers=cabeceras)
    assert respuesta.status_code == 422
    assert "marcados" in respuesta.json()["detail"]


# --- Vencimiento ----------------------------------------------------------------

def test_carga_vence_a_las_24_horas(client: TestClient, auth, db: Session, modulo_id):
    cabeceras = auth("encargado")
    carga = subir(client, cabeceras, modulo_id, excel(filas_base())).json()
    fila_carga = db.get(CargaRiego, carga["id"])
    fila_carga.subido_at = ahora_utc() - timedelta(hours=24, seconds=1)
    db.commit()
    respuesta = client.post(f"{API}/riego/cargas/{carga['id']}/confirmar", headers=cabeceras)
    assert respuesta.status_code == 409
    assert "Sube el archivo otra vez" in respuesta.json()["detail"]
    detalle = client.get(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras).json()
    assert detalle["estado"] == "vencida"
    assert detalle["resumen"]["vencida_motivo"] == "pasaron 24 horas"
    assert db.scalars(select(RiegoRegistro).where(RiegoRegistro.carga_id == carga["id"])).all() == []
    # Una vencida se puede descartar.
    assert client.post(f"{API}/riego/cargas/{carga['id']}/descartar", headers=cabeceras).json()["estado"] == "descartada"


def test_get_marca_vencida_por_tiempo(client: TestClient, auth, db: Session, modulo_id):
    cabeceras = auth("admin")
    carga = subir(client, cabeceras, modulo_id, excel(filas_base())).json()
    assert dt.datetime.fromisoformat(carga["vence_at"]) - dt.datetime.fromisoformat(carga["subido_at"]) == timedelta(hours=24)
    db.get(CargaRiego, carga["id"]).subido_at = ahora_utc() - timedelta(hours=25)
    db.commit()
    assert client.get(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras).json()["estado"] == "vencida"
    assert client.patch(f"{API}/riego/cargas/{carga['id']}", headers=cabeceras, json={
        "grupos": [{"id": carga["grupos"][0]["id"], "aplicar": False}]}).status_code == 409


def test_carga_vence_si_cambio_un_registro_comparado(client: TestClient, auth, db: Session, modulo_id):
    cabeceras = auth("admin")
    primera = subir(client, cabeceras, modulo_id, excel(filas_base())).json()
    segunda = subir(client, cabeceras, modulo_id, excel(filas_base())).json()
    assert client.post(f"{API}/riego/cargas/{primera['id']}/confirmar", headers=cabeceras).status_code == 200
    respuesta = client.post(f"{API}/riego/cargas/{segunda['id']}/confirmar", headers=cabeceras)
    assert respuesta.status_code == 409
    # La carga queda vencida aunque la petición terminó en error (excepción documentada).
    db.expire_all()
    assert db.get(CargaRiego, segunda["id"]).estado.value == "vencida"
    assert "cambió el registro vigente" in db.get(CargaRiego, segunda["id"]).resumen["vencida_motivo"]


# --- Validación del archivo ---------------------------------------------------------

def _rehacer_zip(contenido: bytes, reemplazos: dict[str, bytes]) -> bytes:
    origen = zipfile.ZipFile(io.BytesIO(contenido))
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as destino:
        for info in origen.infolist():
            destino.writestr(info.filename, reemplazos.pop(info.filename, origen.read(info.filename)))
        for nombre, datos in reemplazos.items():
            destino.writestr(nombre, datos)
    return salida.getvalue()


BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>&lol4;</t></si></sst>"""

XXE = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///c:/windows/win.ini">]>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>&xxe;</t></si></sst>"""


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, XXE], ids=["billion_laughs", "xxe"])
def test_excel_malicioso_con_entidades_rechazado(client: TestClient, auth, db: Session, modulo_id, payload):
    malicioso = _rehacer_zip(excel(filas_base()), {"xl/sharedStrings.xml": payload})
    respuesta = subir(client, auth("admin"), modulo_id, malicioso)
    assert respuesta.status_code == 422
    assert "XML no permitido" in respuesta.json()["detail"]
    assert db.scalars(select(CargaRiego)).all() == []


def test_excel_con_dtd_en_workbook_rechazado(client: TestClient, auth, modulo_id):
    contenido = excel(filas_base())
    libro = zipfile.ZipFile(io.BytesIO(contenido)).read("xl/workbook.xml")
    con_dtd = b'<?xml version="1.0"?><!DOCTYPE workbook [<!ENTITY a "b">]>' + libro
    assert con_dtd != libro
    respuesta = subir(client, auth("admin"), modulo_id, _rehacer_zip(contenido, {"xl/workbook.xml": con_dtd}))
    assert respuesta.status_code == 422 and "XML no permitido" in respuesta.json()["detail"]


def test_bomba_zip_rechazada(client: TestClient, auth, modulo_id):
    bomba = _rehacer_zip(excel(filas_base()), {"xl/media/relleno.xml": b"<a>" + b"0" * 20_000_000 + b"</a>"})
    respuesta = subir(client, auth("admin"), modulo_id, bomba)
    assert respuesta.status_code == 422
    assert "compresión anómala" in respuesta.json()["detail"]


@pytest.mark.parametrize(("nombre", "contenido", "mensaje"), [
    ("riego.xls", b"PK\x03\x04resto", ".xlsx"),
    ("riego.csv", b"fecha,turno\n", ".xlsx"),
    ("riego.xlsx", b"", "vacío"),
    ("riego.xlsx", b"%PDF-1.7 no es un excel", "firma"),
    ("riego.xlsx", b"PK\x03\x04" + b"\x00" * 100, "ZIP dañado"),
])
def test_archivo_no_xlsx_rechazado(client: TestClient, auth, modulo_id, nombre, contenido, mensaje):
    respuesta = subir(client, auth("admin"), modulo_id, contenido, nombre=nombre)
    assert respuesta.status_code == 422, respuesta.text
    assert mensaje in respuesta.json()["detail"]


def test_zip_sin_partes_de_excel_rechazado(client: TestClient, auth, modulo_id):
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as z:
        z.writestr("hola.txt", "no soy un excel")
    respuesta = subir(client, auth("admin"), modulo_id, salida.getvalue())
    assert respuesta.status_code == 422 and "faltan partes" in respuesta.json()["detail"]


def test_hoja_y_columnas(client: TestClient, auth, modulo_id):
    cabeceras = auth("admin")
    respuesta = subir(client, cabeceras, modulo_id, excel(filas_base(), hoja="Hoja1"))
    assert respuesta.status_code == 422 and "hoja MOD5" in respuesta.json()["detail"]
    respuesta = subir(client, cabeceras, modulo_id, excel([], cabecera=CABECERA[:-1]))
    assert respuesta.status_code == 422
    assert "Cantidad de riego (m3 por hectarea)" in respuesta.json()["detail"]
    respuesta = subir(client, cabeceras, modulo_id, excel([]))
    assert respuesta.status_code == 422 and "hoja MOD5" in respuesta.json()["detail"]
    # Filas sin fecha/turno/hora: leer_riego las descarta y no queda ninguna.
    respuesta = subir(client, cabeceras, modulo_id, excel([[None, "ENSUEÑO 1", "EN01-MOD5", None, 1,
                                                            None, None, 10, 10, 1]]))
    assert respuesta.status_code == 422 and "no trae filas" in respuesta.json()["detail"]


def test_maximo_de_filas(client: TestClient, auth, modulo_id, monkeypatch):
    monkeypatch.setattr(carga_riego_service, "MAX_FILAS", 5)
    respuesta = subir(client, auth("admin"), modulo_id, excel(filas_base()))
    assert respuesta.status_code == 422 and "máximo de 5 filas" in respuesta.json()["detail"]


def test_archivo_demasiado_grande_413(client: TestClient, auth, modulo_id, monkeypatch):
    from app.core.config import settings

    cabeceras = auth("admin")
    monkeypatch.setattr(settings, "upload_max_mb", 1)
    grande = b"PK\x03\x04" + b"\x00" * (1024 * 1024 + 10)
    assert subir(client, cabeceras, modulo_id, grande).status_code == 413
    # Por debajo del margen del multipart pero por encima del límite del archivo: también 413.
    assert archivo_excel.max_bytes() == 1024 * 1024
    with pytest.raises(archivo_excel.ArchivoDemasiadoGrande):
        archivo_excel.leer_limitado(io.BytesIO(b"x" * (1024 * 1024 + 1)))


def test_subida_sin_archivo_o_modulo(client: TestClient, auth, modulo_id):
    cabeceras = auth("admin")
    respuesta = client.post(f"{API}/riego/cargas", headers=cabeceras, data={"modulo_id": str(modulo_id)})
    assert respuesta.status_code == 422
    respuesta = client.post(f"{API}/riego/cargas", headers=cabeceras,
                            files={"archivo": ("r.xlsx", excel(filas_base()), XLSX)}, data={"modulo_id": "abc"})
    assert respuesta.status_code == 422
    assert subir(client, cabeceras, 999999, excel(filas_base())).status_code == 404


def test_nombre_saneado():
    assert archivo_excel.nombre_saneado("C:\\Users\\x\\riego<script>.xlsx") == "riego_script_.xlsx"
    assert archivo_excel.nombre_saneado("../../etc/passwd") == "passwd.xlsx"
    assert archivo_excel.nombre_saneado("\u202eslx.exe") == "slx.exe.xlsx"
    assert len(archivo_excel.nombre_saneado("a" * 400 + ".xlsx")) == 255
