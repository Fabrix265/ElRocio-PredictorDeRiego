import datetime as dt

import numpy as np

from riego_ml.utils.tiempo import minutes_to_hhmm, to_minutes


def test_hora_simple():
    assert to_minutes(dt.time(16, 47)) == 16 * 60 + 47


def test_hora_excel_mayor_a_24h_cruza_medianoche():
    # Excel guarda 25:38 como 1900-01-01 01:38
    assert to_minutes(dt.datetime(1900, 1, 1, 1, 38)) == 1440 + 98


def test_texto_y_vacios():
    assert to_minutes("05:30") == 330
    assert np.isnan(to_minutes(None))
    assert np.isnan(to_minutes(""))


def test_formato_hhmm_modulo_24h():
    assert minutes_to_hhmm(1440 + 98) == "01:38"
    assert minutes_to_hhmm(float("nan")) == ""
