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
    etiqueta = f"Orden: por {orden or 'turno'}"
    if formato == "xlsx":
        hoja = load_workbook(io.BytesIO(r.content)).active
        assert hoja["A4"].value == etiqueta
        filas = [(f[0], f[1]) for f in hoja.iter_rows(min_row=6, max_row=9, values_only=True)]
        assert hoja["G10"].value == "=SUM(G6:G9)"
    else:
        assert r.content.startswith(b"%PDF")
        assert etiqueta in [llamada.args[0] for llamada in parrafo.call_args_list]
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
