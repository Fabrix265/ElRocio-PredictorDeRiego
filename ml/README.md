# Machine learning

Modulo de extraccion y procesamiento de datos para el predictor de riego.

## Instalacion

Desde la raíz del repositorio:

```powershell
python -m venv ml/.venv
ml\.venv\Scripts\Activate.ps1
pip install -r ml/requirements.txt
```

## Extraccion de datos

Los scripts estan en `ml/src/riego_ml/data_extraction/` y se mantienen fuera de git.

Las credenciales se leen directamente de variables de entorno:

```powershell
$env:PHYTECH_API_KEY="..."
$env:PHYTECH_API_SECRET="..."
$env:PHYTECH_API_BASE_URL="https://us-api.phytech.com"

$env:WEATHERLINK_API_KEY="..."
$env:WEATHERLINK_API_SECRET="..."
$env:WEATHERLINK_API_BASE_URL="https://api.weatherlink.com/v2"
```

Ejecucion (desde la raíz del repositorio):

```powershell
python ml/src/riego_ml/data_extraction/descargar_phytech.py
python ml/src/riego_ml/data_extraction/descargar_weatherlink.py
```

## Configuracion

La configuracion no secreta esta centralizada en `ml/src/riego_ml/settings.py`: modos, anos, series activas, reintentos, zona horaria y rutas.

Salidas:

- `ml/data/raw/phytech/`
- `ml/data/raw/WeatherLink/`
- `ml/cache/`
- `ml/logs/log_descarga_phytech.txt`
- `ml/logs/log_descarga_weatherlink.txt`

Los datos, caches, logs y scripts de extraccion no se versionan.
