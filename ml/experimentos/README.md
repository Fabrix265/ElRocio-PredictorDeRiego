# Experimentos – buscar mejores modelos para el plan de riego

Carpeta **separada del pipeline en uso**: no cambia `ml/models/`, `ml/config/pipeline.yaml`,
la lógica de `ml/src/riego_ml/` ni el backend. Solo lee las tablas del paso 2
(`ml/data/processed/`) y reutiliza las funciones de `riego_ml`.

## Cómo correr

Desde la raíz del repositorio:

```powershell
ml/.venv/Scripts/python ml/experimentos/ejecutar.py                 # todo (~1-2 h)
ml/.venv/Scripts/python ml/experimentos/ejecutar.py --rapido        # solo dev5 + final, sin ajuste
ml/.venv/Scripts/python ml/experimentos/ejecutar.py --solo reporte  # rehace el Excel con lo calculado
```

Resultados en `ml/reports/experimentos/<carpeta>/` (fuera de git):
`comparativa_experimentos.xlsx`, `resumen.md` y `datos/*.csv`.

## Protocolo

| Bloque | Fechas | Uso |
|---|---|---|
| dev1 … dev5 | 5 semestres, 2023-03-16 a 2025-09-15 | Cada candidato aprende con todo lo anterior (7 días de separación) y se mide en el semestre. **Se elige por el promedio de los 5.** |
| final | 2025-09-23 a 2026-11-04 | El mismo test del modelo en uso. Aprende con todo lo anterior al 2025-09-15. **Solo se informa.** |

El modelo en uso se reproduce con la misma receta en cada período, así la comparación es justa.
Los candidatos marcados `ESCENARIO` usan información que no existe a la medianoche
(p. ej. la hora real del 1er ciclo); se informan para ver el potencial, nunca se eligen.

## Qué se prueba

| Archivo | Salida | Candidatos |
|---|---|---|
| `exp_n_ciclos.py` | N° de ciclos | modelo en uso, referencias, Markov, RF, XGBoost, LightGBM, CatBoost, Extra Trees, HistGB, logística, peso reciente, votación, "cambio seguro" con umbrales reales, predecir el cambio (delta), dos etapas |
| `exp_ciclo.py` | Hora de inicio y m3/ha (+ duración derivada) | modelo en uso, referencias, RF, XGBoost, LightGBM, CatBoost, Extra Trees, HistGB, Ridge, objetivos absoluto/Huber, peso reciente, últimos 2 años, promedios de modelos, "sobre lo habitual", hiperparámetros ajustados; para la hora además: estructura del día, reglas de horario, franja, escenarios |
| `exp_rangos.py` | Rangos p10–p90 | receta en uso, margen móvil 30/60/90 días, valor predicho ± margen |
| `exp_plan.py` | Plan completo | el plan en uso vs la mejor combinación (y cada pieza por separado) con `PlanRiego` |
