import numpy as np
import pandas as pd

from riego_ml.modeling.especiales import (
    ClasificadorDosis,
    OrdinalLogistico,
    Persistencia,
    TransicionNCiclos,
)


def _datos(n=300, seed=0):
    rng = np.random.default_rng(seed)
    prev = rng.integers(1, 4, n)
    y = np.where(rng.random(n) < 0.8, prev, rng.integers(1, 4, n))   # 80 % repite lo de ayer
    X = pd.DataFrame({"prev_n_ciclos": prev.astype(float), "mes": rng.integers(1, 13, n),
                      "Turno": rng.choice(["TE01", "TE02"], n), "x": rng.normal(size=n)})
    return X, y


def test_transicion_aprende_la_inercia():
    X, y = _datos()
    modelo = TransicionNCiclos().fit(X, y)
    assert (modelo.predict(X) == X["prev_n_ciclos"]).mean() > 0.9
    sin_ayer = X.head(3).assign(prev_n_ciclos=np.nan)
    assert len(modelo.predict(sin_ayer)) == 3


def test_ordinal_devuelve_probabilidades_validas():
    X, y = _datos()
    modelo = OrdinalLogistico(["Turno"], ["prev_n_ciclos", "x"]).fit(X, y)
    proba = modelo.predict_proba(X)
    assert proba.shape == (len(X), 3)
    assert np.all(proba >= 0)
    assert set(modelo.predict(X)) <= {1, 2, 3}


def test_dosis_devuelve_valores_del_catalogo():
    rng = np.random.default_rng(1)
    X = pd.DataFrame({"a": rng.normal(size=400), "Turno": "TE01"})
    y = np.where(X["a"] > 0, 30.0, 15.0) + rng.normal(0, 0.3, 400)
    modelo = ClasificadorDosis(["Turno"], ["a"], {"n_estimators": 20}).fit(X, y)
    assert set(np.unique(modelo.predict(X))) <= set(modelo.dosis_)


def test_persistencia_usa_respaldo_por_grupo():
    X = pd.DataFrame({"prev": [10.0, np.nan], "Turno": ["TE01", "TE01"]})
    modelo = Persistencia("prev", ("Turno",)).fit(X, [12.0, 14.0])
    assert modelo.predict(X).tolist() == [10.0, 13.0]
