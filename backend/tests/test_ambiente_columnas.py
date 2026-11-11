"""La tabla derivada ambiente_diario tiene exactamente las columnas de riego_ml."""

from riego_ml.dataset.unir import columnas_ambiente

from app.models import AmbienteDiario
from app.models.datos import COLUMNAS_AMBIENTE


def test_columnas_ambiente_coinciden_con_riego_ml():
    esperadas = [c.lower() for c in columnas_ambiente()]
    assert list(COLUMNAS_AMBIENTE) == esperadas
    columnas_tabla = set(AmbienteDiario.__table__.columns.keys())
    banderas = {"tiene_meteo", "tiene_suelo", "tiene_planta"}
    propias = {"id", "fundo_id", "fecha", "created_at", "updated_at"}
    assert columnas_tabla == set(esperadas) | banderas | propias
