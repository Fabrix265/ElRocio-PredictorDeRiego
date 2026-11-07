"""Pipeline de predicción del plan de riego de El Rocío."""

import warnings

# Aviso interno de scikit-learn al paralelizar predicciones con joblib (inofensivo).
warnings.filterwarnings("ignore", message=r".*sklearn\.utils\.parallel\.delayed.*")
