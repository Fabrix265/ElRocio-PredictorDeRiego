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
data/raw/data_riego.xlsx (base) ┐
data/raw/data_metereologica.xlsx├─(1) unir_datos ──► data/interim/  riego_unido.csv, ambiente_diario.csv, dataset_unido.xlsx
data/raw/data_phytech.xlsx      ┘
                                  (2) preparar_dataset ──► data/processed/  turno_dia.csv, ciclos.csv, columnas.json, dataset_entrenamiento.xlsx
                                  (3) entrenar ──► models/plan_riego/modelo_plan_riego.joblib + reports/metricas_modelos.xlsx
                                  (4) predecir ──► reports/plan_riego_<fecha>.xlsx
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
      phytech.py                  Suelo (medio y al cierre del día) + planta
      phytech_crudo.py            Descargas crudas de la API -> data_phytech.xlsx
    dataset/
      unir.py                     Paso 1: riego + ambiente del mismo día y calendario diario
      limpieza.py                 Reglas de descarte de ciclos y tabla turno-día
      features.py                 Features sin fuga (todo lo conocido a las 00:00 del día)
      preparar.py                 Paso 2: tablas de entrenamiento y features para predecir
    modeling/
      estimadores.py              RF, XGBoost, SVR/SVC, MLP y persistencia
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

La **duración** se deriva del volumen con el caudal de cada turno
(`duracion = m3/ha × min_por_m3ha`, mediana histórica): el registro muestra que
duración y volumen son proporcionales por turno, así que volumen, duración y hora de fin
siempre quedan coherentes. El horario final ordena los ciclos y evita solapamientos.

Familias comparadas: Random Forest, XGBoost, SVR/SVC y MLP, más la **persistencia**
("repetir lo de ayer") como un candidato más. Protocolo:

- Split temporal por fechas: train → (7 días) → validación → (7 días) → test.
- Cada target elige el modelo con mejor **validación** (F1 macro para `n_ciclos`, RMSE para
  regresión). El test solo se reporta. Luego el elegido se reentrena con todos los datos.
- Se evalúa también el **plan completo** en test (con `n_ciclos` predicho).
- `--tuning` activa una búsqueda aleatoria de hiperparámetros con folds temporales.

### Resultados actuales (test: 2024-06-23 a 2025-04-24, no usado para elegir)

| Target | Elegido (por validación) | Test | Persistencia en test |
|---|---|---|---|
| `n_ciclos` | persistencia | acierto 0,81 · ±1 ciclo 0,96 | — |
| `riego_m3ha` | Random Forest | RMSE 4,6 · MAE 3,0 · R² 0,54 | RMSE 5,3 · MAE 2,4 |
| `inicio_min` | Random Forest | RMSE 148 min · R² 0,76 | RMSE 199 min |
| `duracion_min` (derivada) | RF + caudal del turno | RMSE 14 min · R² 0,45 | — |

Para `n_ciclos` ningún modelo de ML superó a "repetir lo de ayer" (RF: acierto 0,74): el
número de ciclos depende de decisiones operativas con mucha inercia que las variables
disponibles no explican. La persistencia queda elegida de forma automática por validación;
si con más datos un modelo la supera, se elegirá ese.

Reporte: `reports/metricas_modelos.xlsx` (hojas `Resumen`, `Comparacion`,
`Confusion_n_ciclos`, `Importancias`, `Plan_test`, `Split`).

## Paso 4 – Predicción

```powershell
python ml/src/riego_ml/pipelines/predecir.py                          # día siguiente al último registro
python ml/src/riego_ml/pipelines/predecir.py --fecha 2025-04-25 --dias 3
```

Genera `Plan_por_turno` (1 fila por turno con los ciclos en columnas) y `Plan_por_ciclo`.
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
