# Machine learning – Plan de riego El Rocío

Predice, **antes de que empiece el día**, el plan de riego de cada turno del módulo:

| Salida | Descripción |
|---|---|
| `Fecha`, `Turno` | Día y turno (TE01–TE05) planificados |
| `n_ciclos` | Número de ciclos del turno ese día (1–5; 5 = "5 o más") |
| `riego_m3ha` / `riego_m3` | Volumen de cada ciclo (m3/ha y m3) |
| `duracion_min` | Duración de cada ciclo en minutos |
| `hora_inicio` / `hora_fin` | Horario de cada ciclo (HH:MM) |

## Pipeline

```text
data/raw/phytech/completo/*  ──(0) limpiar_phytech ──► data/raw/data_phytech.xlsx
data/raw/data_riego_historico.xlsx (base) ┐
data/raw/data_metereologica.xlsx├─(1) unir_datos ──► data/interim/  riego_unido.csv, ambiente_diario.csv, dataset_unido.xlsx
data/raw/data_phytech.xlsx      ┘
                                  (2) preparar_dataset ──► data/processed/  turno_dia.csv, ciclos.csv, columnas.json, dataset_entrenamiento.xlsx
                                  (3) entrenar ──► models/plan_riego/{actual,versiones/<corrida>}/ + reports/entrenamientos/<corrida>/
                                  (4) predecir ──► reports/predicciones/plan_riego_<fecha>.xlsx
```

Desde la raíz del repositorio:

```powershell
pip install -r ml/requirements.txt
python ml/src/riego_ml/pipelines/ejecutar_todo.py               # pasos 1-3
python ml/src/riego_ml/pipelines/predecir.py --fecha 2025-04-25  # paso 4
```

Cada paso también se puede correr por separado (`limpiar_phytech.py`, `unir_datos.py`,
`preparar_dataset.py`, `entrenar.py`, `predecir.py`). Toda la configuración está en
[`config/pipeline.yaml`](config/pipeline.yaml).

## Estructura

```text
ml/
  config/pipeline.yaml            Configuración única (rutas, limpieza, split, modelos)
  src/riego_ml/
    config.py                     Carga y validación del YAML
    settings.py                   Rutas del proyecto y constantes de extracción
    sources/                      Lectura y saneamiento de cada fuente
      riego.py                    Registro MOD5 (base): horas, cruce de medianoche, área
      meteo.py                    Estación cada 30 min -> resumen diario
      phytech.py                  Suelo (medio, al cierre y rango diario) + planta
      ndvi.py                     NDVI del plot (imágenes satelitales de Phytech)
      phytech_crudo.py            Descargas crudas de la API -> data_phytech.xlsx
    dataset/
      unir.py                     Paso 1: riego + ambiente del mismo día y calendario diario
      limpieza.py                 Reglas de descarte de ciclos y tabla turno-día
      features.py                 Features sin fuga (todo lo conocido a las 00:00 del día)
      preparar.py                 Paso 2: tablas de entrenamiento y features para predecir
    modeling/
      estimadores.py              RF, XGBoost, LightGBM, CatBoost, SVR/SVC, MLP
      especiales.py               Referencias, transición, ordinal, dosis y rangos por cuantiles
      reporte.py / graficos.py    Excel, gráficos e historial de corridas
      split.py                    Split temporal con gap
      metricas.py                 Métricas de regresión y clasificación
      entrenamiento.py            Paso 3: compara, selecciona y reentrena
      planificador.py             PlanRiego: n_ciclos -> ciclos -> horario
      prediccion.py               Predicción de una o varias fechas
    pipelines/                    CLIs de cada paso + ejecutar_todo.py
    utils/                        Excel, horas, logging, JSON
    data_extraction/              Descarga de APIs (fuera de git)
  tests/                          Pruebas de horas, limpieza, features, split y horario
```

## Paso 0 – Phytech crudo

`limpiar_phytech.py` toma `data/raw/phytech/completo/` (archivos `SoilHourlyData_*` y
`ProjectsDailyData_*` del área 12537, plot 70208 "ENSUEÑO 1") y genera `data_phytech.xlsx`
con las hojas `Suelo_horario`, `Suelo_diario`, `Planta_diario`, `Leyenda` y `Diagnostico`.

- Humedad fuera de 5–60 % se anula (las lecturas ~0 % son sonda sin contacto, no suelo seco).
- Temperatura de suelo fuera de 5–45 °C se anula.
- Lecturas alineadas a la hora y rejilla horaria completa (las horas sin dato quedan visibles).
- No se interpola ni se rellena nada.

## Paso 1 – Unión (riego como base)

- **Riego** (`MOD5`): `Fecha` es el día de inicio. Las horas de fin mayores a 24 h que Excel
  guarda como `1900-01-01 HH:MM` se interpretan como del día siguiente. `inicio_min` y
  `fin_min` son minutos desde las 00:00 de `Fecha`.
- **Meteorología**: se sanea cada lectura de 30 min antes de agregar (sensor caído con
  T = 0 y HR = 0, rangos físicos, ETo > 0,8 mm en 30 min, lecturas fuera de la grilla que
  duplicaban bloques). Un día con < 75 % de lecturas válidas deja esa variable vacía.
- **Phytech**: sensor 907557; humedad media del día y "al cierre" (21–23 h) por profundidad;
  MDS, crecimiento del tronco e índice de estrés.
- Llave de unión: `Fundo` + `Fecha`. `ambiente_diario.csv` es un calendario continuo para
  poder calcular rezagos sin huecos.

## Paso 2 – Limpieza y features

Reglas de limpieza (los descartados quedan en la hoja `Descartados` con su motivo):

- Apertura fallida: duración < 5 min o volumen < 2 m3/ha.
- Duplicados (mismo turno, fecha e inicio).
- Los ciclos se renumeran por hora de inicio; los que se solapan con el anterior se marcan.
- `dia_incompleto = 1` si ese día se registraron menos turnos que los habituales (no se evalúa).

Features (todas conocidas a las 00:00 del día D, verificado en `tests/test_features.py`):

- Calendario: mes, día de la semana, estacionalidad (`doy_sin`, `doy_cos`), turno.
- Meteo del día anterior y ventanas (ETo media 3/7 días, lluvia acumulada 7 días…).
- Suelo: cambios en 24 h de la humedad (zona radicular y 45 cm).
- Planta del día anterior (MDS, crecimiento, estrés) y MDS medio 3 días.
- Riego previo del mismo turno (ciclos, m3/ha, horarios de ayer y medias 3/7 días) y del
  mismo número de ciclo (para los modelos por ciclo).

Features extendidas (`preparacion.features_extendidas: true`):

- Rotación de turnos: orden y hora de arranque de cada turno ayer, desfase respecto del
  arranque del módulo y del turno anterior; inicio de hace 7 días.
- Estabilidad: días desde el último cambio de n° de ciclos, cambios en 14 días, tendencia.
- Agua: balance hídrico 7 días (ETo × 10 − riego aplicado) y reposición (riego / ETo).
- Horas con T > 30 °C, tendencia de la ETo, anomalía del MDS, crecimiento acumulado,
  respuesta diaria del suelo (rango de humedad a 45/60 cm), NDVI y feriados de Perú.
- Por ciclo: m3/ha e inicio de hace 7 días, dosis habitual (mediana 7 días), desfase del ciclo.

Fuentes revisadas que **todavía no se usan** porque no se cruzan con el histórico de riego:
`PROGRAMA DE RIEGO 2026-2027.xlsx` (semanas 27-44 de 2026), etapa de la hoja `siga` (un solo
valor), riegos planificados / recomendaciones Daisy / pronóstico de Phytech (una sola captura).
Con el `data_riego` actualizado a 2026 el programa de riego pasa a ser candidato.

> **Niveles absolutos de humedad del suelo fuera del modelo** (`usar_suelo_absoluto: false`).
> El sensor cambió de régimen entre temporadas (a 45 cm la media pasa de ~20 % en el período
> de entrenamiento a ~28 % en el de test; 15/30 cm y zona radicular casi no existen antes de
> 2023). Con esas variables el error de m3/ha en test pasaba de ~4,6 a ~12,5 m3/ha. Se
> conservan en el dataset para revisión.

## Paso 3 – Modelos

Tres modelos componen el plan:

1. **Clasificador `n_ciclos`** (tabla turno-día).
2. **Regresor `riego_m3ha`** por ciclo.
3. **Regresor `inicio_min`** por ciclo.

La **duración** se deriva del volumen con el caudal reciente de cada turno
(`duracion = m3/ha × minutos por m3/ha del turno en los últimos 30 días`). El caudal de las
válvulas subió 8–18 % desde 2024, por eso se usa el reciente y no la mediana histórica
(con el m3/ha real: error ±1,5 min contra ±5,2 min). Así volumen, duración y hora de fin
quedan coherentes. El horario final ordena los ciclos y evita solapamientos.

Candidatos que compiten por cada target (todos en el mismo reporte):

| Tipo | Modelos | Target |
|---|---|---|
| ML | Random Forest, XGBoost, LightGBM, CatBoost (SVR y MLP desactivados) | los tres |
| Referencias | persistencia (ayer), media 7 días, semana pasada | los tres |
| Específicos | transición tipo Markov, logística ordinal, persistencia salvo cambio seguro | `n_ciclos` |
| Específicos | clasificador de dosis programadas | `riego_m3ha` |

Además se entrenan **rangos p10–p90** (LightGBM por cuantiles) para m3/ha e inicio, con un
margen calibrado en validación para que el rango cubra ~80 % de los casos. Protocolo:

- Split temporal por fechas: train → (7 días) → validación → (7 días) → test.
- Cada target elige el modelo con mejor **validación** (F1 macro para `n_ciclos`, RMSE para
  regresión). El test solo se reporta. Luego el elegido se reentrena con todos los datos.
- Se evalúa también el **plan completo** en test (con `n_ciclos` predicho).
- `--tuning` activa una búsqueda aleatoria de hiperparámetros con folds temporales.

### Resultados actuales

Datos: `data_riego_historico.xlsx`, abr-2021 a nov-2026 (20.764 ciclos válidos).
Test de la corrida: 2025-09-23 a 2026-11-04 (no usado para elegir).

| Target | Elegido (por validación) | Test |
|---|---|---|
| `n_ciclos` | persistencia salvo cambio seguro | acierto 0,81 · ±1 ciclo 0,97 |
| `riego_m3ha` | XGBoost | RMSE 4,9 · MAE 3,2 |
| `inicio_min` | XGBoost | RMSE 155 min · MAE 1 h 56 min |
| `duracion_min` (derivada, caudal 30 días) | XGBoost + caudal | MAE 8,7 min · sesgo +0,5 min |
| Plan: riego total turno-día | — | RMSE 9,4 m3/ha |

Comparación justa (mismo período 2025-09-23 → 2026-11-04, que ninguno vio):
modelo anterior (datos hasta abr-2025) vs. modelo nuevo reentrenado con datos hasta
2025-09-15 (`evaluar_modelo.py --reentrenar-hasta 2025-09-15`): m3/ha MAE 3,33 → 3,10,
duración MAE 10,5 → 8,4 min (sesgo +4,7 → −0,4), plan total RMSE 9,9 → 9,3, cobertura de
rangos 68 % → 75 %; n° de ciclos igual (81 %); hora de inicio algo peor (MAE 113 → 119 min).

### Reportes de cada entrenamiento

Cada corrida crea su propia carpeta (las anteriores se conservan para comparar) y se
agrega una fila a `reports/historial_entrenamientos.xlsx` (datos usados, features, modelo
elegido y métricas de test). Así se ve el efecto de actualizar datos, features o modelos.

```text
reports/entrenamientos/<AAAA-MM-DD_HHMM>/
  metricas_modelos.xlsx      Reporte principal
  graficos/                  01_comparacion_n_ciclos.png ... 16_horario_dia_tipico.png
  datos/                     comparacion_modelos.csv, predicciones_test_*.csv, resumen.json
```

Hojas de `metricas_modelos.xlsx`:

| Hoja | Contenido |
|---|---|
| `Resumen` | Datos de la corrida (fechas del split, tamaños) y modelo elegido por target vs persistencia |
| `Comp_n_ciclos`, `Comp_m3ha`, `Comp_inicio` | Todos los modelos, validación y test (elegido en azul, mejor valor en verde) |
| `Plan_completo` | Error del plan armado de punta a punta y de duración/fin derivados |
| `Rangos` | Cobertura real del rango p10–p90 en test (sin calibrar y calibrado) |
| `Historial` | Todas las corridas anteriores, para comparar |
| `Por_turno`, `Por_mes` | Errores en test por turno y por mes |
| `Confusion` | Matriz de confusión del número de ciclos |
| `Importancias` | Variables más importantes de RF y XGBoost |
| `Graficos` | Todos los gráficos incrustados |
| `Pred_turno_test`, `Pred_ciclo_test`, `Plan_test` | Real vs predicho, fila por fila |
| `Features` | Variables usadas y excluidas |

### Versiones y evaluación de modelos

Cada entrenamiento se guarda en `models/plan_riego/versiones/<corrida>/` y se copia a
`models/plan_riego/actual/` (el que usa `predecir.py`). Para comparar modelos sobre el
mismo período:

```powershell
python ml/src/riego_ml/pipelines/evaluar_modelo.py --desde 2025-09-23 `
  --modelos ml/models/plan_riego/versiones/2026-11-07_0841 --reentrenar-hasta 2025-09-15
```

Genera `reports/evaluaciones/evaluacion_<desde>_<hasta>.xlsx`.

## Paso 4 – Predicción

```powershell
python ml/src/riego_ml/pipelines/predecir.py                          # día siguiente al último registro
python ml/src/riego_ml/pipelines/predecir.py --fecha 2025-04-25 --dias 3
```

Genera `Plan_por_turno` (1 fila por turno con los ciclos en columnas) y `Plan_por_ciclo`.
Cada ciclo trae también su rango: `riego_m3ha_p10`/`p90`, `duracion_min_p10`/`p90` y
`hora_inicio_desde`/`hasta` (≈80 % de probabilidad de caer dentro).
Usa el historial del paso 1 para las features del día anterior: cuando lleguen datos
nuevos, volver a correr `unir_datos.py`. Para varios días, la predicción es recursiva (el
plan del día D se usa como "riego de ayer" del día D+1).

## Pruebas

```powershell
python -m pytest ml/tests -q
```

## Extracción de datos

Los scripts de `src/riego_ml/data_extraction/` se mantienen fuera de git y leen las
credenciales de variables de entorno (`PHYTECH_API_KEY`, `PHYTECH_API_SECRET`,
`WEATHERLINK_API_KEY`, `WEATHERLINK_API_SECRET`, …). Ver el README raíz.
