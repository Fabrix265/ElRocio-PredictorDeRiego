"""Orden de lectura y cabeceras en las exportaciones de cronogramas."""
import datetime as dt
import io
from unittest.mock import patch

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import Cronograma, CronogramaCiclo, CronogramaEvento, CronogramaTurno, CronogramaVersion
from app.models.enums import OrigenVersion, TipoEventoCronograma
from app.repositories import riego as repo_riego
from app.services import exportar_pdf
from tests.conftest import API


@pytest.fixture
def plan(db):
    crono = Cronograma(modulo_id=1, fecha=dt.date(2026, 11, 14))
    db.add(crono)
    db.flush()
    version = CronogramaVersion(cronograma_id=crono.id, numero=1, origen=OrigenVersion.modelo)
    db.add(version)
    db.flush()
    turnos = repo_riego.turnos_de_modulo(db, 1)[:2]
    # Incluye empate de inicio y un ciclo del día siguiente: no se ordena por HH:MM.
    for turno, inicios in zip(turnos, ((360, 1450), (180, 360))):
        db.add(CronogramaTurno(version_id=version.id, turno_id=turno.id, n_ciclos=2,
                               n_ciclos_modelo=2, area_ha=turno.area_ha, factor_min_por_m3ha=2))
        for ciclo, inicio in enumerate(inicios, start=1):
            fin = inicio + 20
            db.add(CronogramaCiclo(
                version_id=version.id, turno_id=turno.id, ciclo=ciclo,
                riego_m3ha=10, riego_m3=10 * turno.area_ha, duracion_min=20,
                inicio_min=inicio, fin_min=fin,
                hora_inicio=f"{inicio // 60 % 24:02}:{inicio % 60:02}",
                hora_fin=f"{fin // 60 % 24:02}:{fin % 60:02}", fin_dia_siguiente=fin >= 1440,
            ))
    crono.borrador_version_id = version.id
    db.commit()
    return crono, [t.codigo for t in turnos]


@pytest.mark.parametrize("orden", [None, "turno", "hora"])
@pytest.mark.parametrize("formato", ["pdf", "xlsx"])
def test_exportar_orden_y_cabecera(client, auth, db, plan, orden, formato):
    crono, (a, b) = plan
    parametros = {"formato": formato}
    if orden is not None:
        parametros["orden"] = orden
    # Se genera el PDF real y se inspeccionan las filas que recibe su tabla.
    with patch.object(exportar_pdf, "Table", wraps=exportar_pdf.Table) as tabla, \
            patch.object(exportar_pdf, "Paragraph", wraps=exportar_pdf.Paragraph) as parrafo:
        r = client.get(f"{API}/cronogramas/{crono.id}/exportar", params=parametros, headers=auth())
    assert r.status_code == 200, r.text
    etiqueta = "Orden: por horario" if orden == "hora" else "Orden: por turno"
    if formato == "xlsx":
        hoja = load_workbook(io.BytesIO(r.content)).active
        assert hoja["A4"].value == etiqueta
        filas = [(f[0], f[1]) for f in hoja.iter_rows(min_row=6, max_row=9, values_only=True)]
        assert hoja["G10"].value == "=SUM(G6:G9)"
        assert hoja["F10"].value == pytest.approx(20.0)  # m³ totales ÷ ha de los turnos
    else:
        assert r.content.startswith(b"%PDF")
        assert etiqueta in [llamada.args[0] for llamada in parrafo.call_args_list]
        assert tabla.call_args.args[0][-1][5] == "20,00"
        filas = []
        anterior = None
        for f in tabla.call_args.args[0][1:-1]:
            anterior = f[0] or anterior
            filas.append((anterior, f[1]))
    esperado = [(b, 1), (a, 1), (b, 2), (a, 2)] if orden == "hora" else [(a, 1), (a, 2), (b, 1), (b, 2)]
    assert filas == esperado
    evento = db.scalar(select(CronogramaEvento).where(
        CronogramaEvento.cronograma_id == crono.id, CronogramaEvento.tipo == TipoEventoCronograma.exportado))
    assert evento.detalle == {"formato": formato, "orden": orden or "turno"}


@pytest.mark.parametrize("formato", ["pdf", "xlsx"])
def test_exportar_orden_invalido(client, auth, plan, formato):
    crono, _ = plan
    r = client.get(f"{API}/cronogramas/{crono.id}/exportar",
                   params={"formato": formato, "orden": "otro"}, headers=auth())
    assert r.status_code == 422
    assert any(error["loc"] == ["query", "orden"] for error in r.json()["detail"])


def test_versiones_traen_m3_y_m3ha_del_dia(client, auth, db, plan):
    crono, _ = plan
    turnos = repo_riego.turnos_de_modulo(db, 1)[:2]
    area = sum(t.area_ha for t in turnos)
    r = client.get(f"{API}/cronogramas/{crono.id}/versiones", headers=auth())
    assert r.status_code == 200, r.text
    (v,) = r.json()
    assert v["total_m3"] == pytest.approx(round(20 * area, 1))
    assert v["total_m3ha"] == pytest.approx(20.0)  # 2 ciclos de 10 m³/ha en cada turno


def test_listado_trae_agua_y_eto_del_dia_anterior(client, auth, db, plan):
    from app.models import AmbienteDiario, Modulo

    crono, _ = plan
    modulo = db.get(Modulo, 1)
    db.add(AmbienteDiario(fundo_id=modulo.fundo_id, fecha=crono.fecha - dt.timedelta(days=1), eto_mm=3.2))
    db.commit()
    r = client.get(f"{API}/cronogramas", params={"modulo_id": 1, "desde": crono.fecha.isoformat(),
                                                  "hasta": crono.fecha.isoformat()}, headers=auth())
    assert r.status_code == 200, r.text
    (fila,) = r.json()
    assert fila["eto_dia_anterior_mm"] == pytest.approx(3.2) and fila["eto_dia_anterior_pronostico"] is False
    assert fila["version"]["total_m3ha"] == pytest.approx(20.0)
    assert fila["version"]["total_m3"] > 0


def test_listado_usa_eto_del_pronostico_si_no_hay_medida(client, auth, db, plan):
    from app.models import Modulo, PronosticoClima

    crono, _ = plan
    modulo = db.get(Modulo, 1)
    ayer = crono.fecha - dt.timedelta(days=1)
    for capturado, eto in ((ayer - dt.timedelta(days=3), 2.5), (ayer - dt.timedelta(days=1), 3.9)):
        db.add(PronosticoClima(fundo_id=modulo.fundo_id, project_id=1, capturado_fecha=capturado, fecha=ayer, eto_mm=eto))
    db.commit()
    r = client.get(f"{API}/cronogramas", params={"modulo_id": 1, "desde": crono.fecha.isoformat(),
                                                  "hasta": crono.fecha.isoformat()}, headers=auth())
    (fila,) = r.json()
    assert fila["eto_dia_anterior_mm"] == pytest.approx(3.9) and fila["eto_dia_anterior_pronostico"] is True
