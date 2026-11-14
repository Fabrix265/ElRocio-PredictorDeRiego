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
| `exp_total_turno.py` | Total m3/ha por turno-día (lo que usa el riego por pulsos) | persistencia, media 7 días, Ridge, RF, LightGBM, XGBoost × 5 grupos de features; vs el plan en uso (suma de sus ciclos) y efecto en `calculo_pulsos` |

## Total m3/ha por turno-día (`exp_total_turno.py`)

Con riego por pulsos el sistema solo usa el total de m3/ha de cada turno-día
(`backend/app/services/calculo_pulsos.py` arma ciclos, duración y horario). Este experimento
entrena un modelo directo de ese total y lo compara con el modelo en uso. Es independiente de
`ejecutar.py` y tiene su configuración en [`config/total_turno.yaml`](../config/total_turno.yaml).

```powershell
ml/.venv/Scripts/python ml/experimentos/exp_total_turno.py                 # completo (~4 min)
ml/.venv/Scripts/python ml/experimentos/exp_total_turno.py --sin-ajuste --no-guardar-modelo
```

- **Target:** `riego_total_m3ha` (suma de los ciclos aplicados) por turno-día. Los días en que el
  módulo entero no tiene registro cuentan como 0 m3/ha si el hueco dura ≤ 6 días; un hueco más
  largo (2024-10-08 a 2024-10-20) es falta de datos y queda fuera. Los turnos que faltan en un
  día con registros no se agregan (ese día es `dia_incompleto` y no se evalúa).
- **Features:** las del pipeline (`construir_features_turno`, historial observado, todo conocido a
  las 00:00), agrupadas en calendario, riego previo, clima, suelo (solo cambios) y planta.
- **Split y elección:** el del pipeline (train → 7 días → validación → 7 días → test). Se elige
  solo por validación (RMSE, desempate MAE).
- **Comparación:** el modelo en uso guardado vio el test, así que se reproduce su receta con
  `reentrenar_hasta`. Principal: ambos aprenden hasta 2025-09-15 y se miden en el test
  2025-09-23 → fin; secundaria: ambos solo con el train del pipeline. Además, los totales de
  cada modelo pasan por `calculo_pulsos.calcular` con `POR_DEFECTO` y se compara el n° de pulsos
  con el que sale de lo realmente aplicado.
- **Salidas:** `ml/reports/experimentos/total_turno/` (`comparativa_total_turno.xlsx`, `resumen.md`).
  Si el nuevo gana en el test, versión candidata en `ml/models/total_turno/versiones/<fecha>/`
  (+ copia en `candidato/`); no reemplaza a `models/plan_riego/actual` ni toca el backend.
  `exp_total_turno.predecir_total(fecha)` da el total por turno con esa versión.
