# Machine learning

Módulo de extracción de datos y pipeline de predicción de riego por turno para El Rocío.

El pipeline trabaja a nivel **turno**. Para cada turno predice:

- `N_ciclos`: cantidad de ciclos de riego (clasificación 1, 2 o 3).
- Para cada ciclo `k = 1..max_cycles`:
  - `Riego_ciclo_k_m3`: volumen del ciclo en m3.
  - `Hora_inicio_k`: hora de inicio.
  - `Tiempo_ciclo_k_min`: duración en minutos.
  - `Hora_fin_k`: se deriva como `Hora_inicio_k + Tiempo_ciclo_k_min`.
- `Riego_total_m3`: se deriva como la suma de los ciclos activos según `N_ciclos` predicho.

La decisión de predecir inicio y duración, y derivar la hora de fin, evita inconsistencias entre las tres variables de horario. El modo de fin derivado está configurado con `schedule.end_mode: derived`.

## Instalación

Desde la raíz del repositorio:

```powershell
python -m venv ml/.venv
ml\.venv\Scripts\Activate.ps1
pip install -r ml/requirements.txt
```

Dependencias principales: `pandas`, `numpy`, `scikit-learn`, `xgboost`, `matplotlib`, `joblib`, `PyYAML`, `openpyxl` y `xlsxwriter`.

## Estructura

```text
ml/
  config/
    train.yaml                 Configuración principal del entrenamiento
  data/
    raw/                       Datos originales (no versionados)
    processed/                 Datasets procesados, incluida la muestra actual
  models/                      Artefactos entrenados por modelo (no versionados)
  reports/                     Excel, métricas, datasets procesados y figuras (no versionados)
  src/riego_ml/
    config/                    Carga y validación del YAML
    data/                      Fuentes de datos, carga y validación
    preprocessing/             Limpieza de ciclos, parseo de horas y split
    features/                  Agregación ciclo -> turno, features, targets y horarios
    training/
      base.py                  Clase base multi-target
      registry.py              Registro de modelos
      trainer.py               Orquestador del entrenamiento
      models/                  Random Forest, XGBoost, SVR y MLP
    evaluation/                Métricas, gráficos y reporte Excel
    inference/                 Carga de modelos y predicción
    pipelines/                 CLIs de entrenamiento y predicción
    utils/                     Logs, rutas, JSON, reproducibilidad
```

## Datos de entrada

El dataset de muestra está en:

```text
ml/data/processed/dataset_riego_muestra.xlsx
```

Hoja `Dataset`, con una fila por ciclo de riego. Columnas esperadas por defecto:

- `Fecha`, `Fundo`, `Modulo`, `Turno`
- `Nro_ciclo`, `Riego_ciclo_m3`, `Riego_total_m3`
- `Hora_inicio`, `Hora_fin`
- `Temperatura_C`, `Humedad_rel_pct`, `Contraccion_planta_um`, `Radiacion_W_m2`

La agregación a nivel turno calcula:

- `N_ciclos` y `Riego_total_m3` a partir de los ciclos.
- Los targets de cada slot: volumen, inicio y duración.
- Agregados ambientales diarios por fecha: `_mean`, `_min`, `_max`, `_std`.
- Features de fecha: `anio`, `mes`, `dia`, `dia_anio`, `dia_semana`, `semana_iso`.
- `Turno_orden`, derivado del número final del turno (`TA1 -> 1`, `TA2 -> 2`, etc.).

## Configuración

Toda la configuración está en `ml/config/train.yaml`.

Secciones principales:

- `data.source`: tipo (`excel`, `csv`, `parquet`), ruta, hoja y `column_map`.
- `data.categorical_features`: columnas categóricas, por defecto `Fundo`, `Modulo`, `Turno`.
- `data.numeric_features`: features numéricas adicionales. Puede quedar vacío.
- `data.environmental_features`: columnas ambientales que se agregan por fecha.
- `data.max_cycles`: cantidad máxima de ciclos modelados.
- `data.nro_ciclo_column`, `cycle_volume_column`, `start_column`, `end_column`: nombres de columnas del dataset.
- `split`: `group_shuffle` agrupado por `Turno`, con tamaños de test y validación.
- `targets`: columna y clases de `N_ciclos`, columna de total y opción de modelo directo del total.
- `schedule`: separación mínima entre ciclos y modo de hora de fin.
- `models`: parámetros y early stopping por modelo.
- `evaluation`: métricas, gráficos, Excel y cantidad de turnos para los gráficos Gantt.

`column_map` permite adaptar datos externos sin renombrar el archivo. El formato es `nombre_canonico: nombre_en_el_archivo`, por ejemplo:

```yaml
column_map:
  Fecha: fecha_riego
  Turno: turno_operativo
  Riego_ciclo_m3: volumen_m3
```

## Entrenamiento

Desde la raíz del repositorio:

```powershell
python ml/src/riego_ml/pipelines/train.py --config ml/config/train.yaml
```

También se puede ejecutar como módulo:

```powershell
$env:PYTHONPATH="ml/src"
python -m riego_ml.pipelines.train --config ml/config/train.yaml
```

Opciones útiles:

```powershell
python ml/src/riego_ml/pipelines/train.py --models random_forest,xgboost
python ml/src/riego_ml/pipelines/train.py --seed 123 --test-size 0.25
python ml/src/riego_ml/pipelines/train.py --name prueba_riego
```

## Predicción

Con un modelo ya entrenado:

```powershell
python ml/src/riego_ml/pipelines/predict.py `
  --config ml/config/train.yaml `
  --model random_forest `
  --input ml/data/processed/dataset_riego_muestra.xlsx `
  --output ml/reports/predicciones_random_forest.xlsx
```

Si se omite `--input`, se usa `data.source.path` del YAML. La salida puede ser `.xlsx` o `.csv`. El Excel incluye dos hojas: `Predicciones` con todas las columnas y `Resumen` con el horario legible en formato `HH:MM`.

## Modelos

Se entrenan cuatro familias, cada una con un clasificador para `N_ciclos` y un regresor por cada target de ciclo:

- `random_forest`: `RandomForestClassifier` y `RandomForestRegressor`. Early stopping por `warm_start`, agregando árboles por bloques y evaluando en validación.
- `xgboost`: `XGBClassifier` y `XGBRegressor`. Early stopping nativo con `eval_set` y `early_stopping_rounds`.
- `svr`: `SVC` para clasificación y `SVR` para regresión. No usa early stopping; requiere escalado.
- `mlp`: `MLPClassifier` y `MLPRegressor`. Early stopping por épocas con `partial_fit`, paciencia y restauración del mejor modelo.

Los modelos de árboles no escalan las features numéricas. SVR y MLP sí usan `StandardScaler`.

## Validación

El split por defecto es `GroupShuffleSplit` agrupado por `Turno`, de modo que un turno no aparece en train y test a la vez. Se separa primero test y luego validación dentro del resto. El pipeline intenta varias semillas para que las clases de `N_ciclos` estén presentes en train.

Con el dataset de muestra hay muy pocos turnos con un solo ciclo, por lo que puede ocurrir que test no contenga la clase 1. En ese caso las métricas de clasificación se calculan con las clases presentes; el modelo sí aprende la clase 1 si aparece en train.

## Métricas

Regresión:

- `RMSE`, `MAE`, `R2`, `MBE`, `Pearson r`, `KGE`, `NSE`, `PBIAS`, `sMAPE`, `Willmott d`, `MedAE`, `MaxError`.

Clasificación:

- `accuracy`, `balanced_accuracy`, `F1 macro`, `Cohen kappa` y matriz de confusión.

Horarios:

- MAE y RMSE por ciclo para inicio, duración y fin.
- Porcentaje de turnos con orden de horarios válido antes de ajustar solapamientos.

## Salidas

Después de entrenar:

```text
ml/models/<modelo>/
  model.joblib                 Modelo multi-target
  preprocessor.joblib          ColumnTransformer ajustado
  metadata.json                Features, targets, split, métricas y entorno
  metrics.json                 Métricas del modelo
  histories.json               Historial de early stopping

ml/reports/
  metricas_modelos.xlsx        Reporte consolidado
  dataset_turno.csv            Dataset agregado por turno
  dataset_ciclo_limpio.csv     Dataset de ciclos limpio
  dataset_resumen.json         Resumen del dataset
  config_usada.yaml/json       Configuración efectiva
  run_metadata.json            Metadatos de la corrida
  figures/<modelo>/            Gráficos por modelo y target
  figures/comparacion/         Comparación entre modelos
```

Hojas del Excel:

- `Resumen_Regresion`, `Resumen_Clasificacion`, `Horarios`, `Ranking`
- `Predicciones_Turno`, `Predicciones_Ciclo`
- `Confusion_N_Ciclos`, `Errores_Top`, `Metricas_Grupo`
- `Targets`, `Modelos`, `Configuracion`

## Cambiar a datos reales

1. Copiar el archivo real a `ml/data/raw/` o a `ml/data/processed/`.
2. Actualizar `data.source.path`, `data.source.type` y `data.source.sheet` en `ml/config/train.yaml`.
3. Si los nombres de columnas cambian, usar `column_map`.
4. Ajustar `data.environmental_features` y `data.max_cycles` según los datos disponibles.
5. Verificar que existan las columnas de ciclo, volumen, inicio y fin configuradas.
6. Ejecutar el entrenamiento y revisar `ml/reports/metricas_modelos.xlsx` y las figuras.

El pipeline no requiere cambiar código para pasar de Excel a CSV o Parquet, siempre que la configuración apunte a la fuente correcta.

## Extracción de datos

Los scripts de extracción están en `ml/src/riego_ml/data_extraction/` y se mantienen fuera de git.

Las credenciales se leen de variables de entorno:

```powershell
$env:PHYTECH_API_KEY="..."
$env:PHYTECH_API_SECRET="..."
$env:PHYTECH_API_BASE_URL="https://us-api.phytech.com"

$env:WEATHERLINK_API_KEY="..."
$env:WEATHERLINK_API_SECRET="..."
$env:WEATHERLINK_API_BASE_URL="https://api.weatherlink.com/v2"
```

Ejecución:

```powershell
python ml/src/riego_ml/data_extraction/descargar_phytech.py
python ml/src/riego_ml/data_extraction/descargar_weatherlink.py
```

Salidas de extracción:

- `ml/data/raw/phytech/`
- `ml/data/raw/WeatherLink/`
- `ml/cache/`
- `ml/logs/log_descarga_phytech.txt`
- `ml/logs/log_descarga_weatherlink.txt`

Los datos, cachés, logs, modelos, reportes y scripts de extracción no se versionan.
