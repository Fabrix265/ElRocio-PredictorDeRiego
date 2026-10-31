# Sistema de prediccion de riego para el grupo el rocio

Monorepo para predecir las necesidades de riego de cultivos agricolas a partir de datos historicos de APIs y sensores. El sistema transforma esos datos en recomendaciones de metros cubicos, ciclos y minutos de riego, y esta orientado a un modulo de un fundo de El Rocio.

## Estructura

```text
backend/    API FastAPI
frontend/   Aplicacion React + Vite
ml/         Extraccion, procesamiento y modelos
docs/       Documentacion tecnica y papers
```

## Requisitos

- Python 3.11+
- Node.js 20.19+ o 22.12+
- npm 10+

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Machine learning

Desde la raíz del repositorio:

```powershell
python -m venv ml/.venv
ml\.venv\Scripts\Activate.ps1
pip install -r ml/requirements.txt
```

Los scripts de extraccion viven en `ml/src/riego_ml/data_extraction/` y estan ignorados por git. Las credenciales se pasan como variables de entorno en la sesion, no se leen desde un archivo `.env`:

```powershell
$env:PHYTECH_API_KEY="..."
$env:PHYTECH_API_SECRET="..."
$env:WEATHERLINK_API_KEY="..."
$env:WEATHERLINK_API_SECRET="..."
python ml/src/riego_ml/data_extraction/descargar_phytech.py
python ml/src/riego_ml/data_extraction/descargar_weatherlink.py
```

Salidas:

- `ml/data/raw/phytech/`
- `ml/data/raw/WeatherLink/`
- `ml/cache/`
- `ml/logs/`

## Seguridad

No se versionan credenciales, archivos `.env`, datos descargados, caches, logs ni los scripts de extraccion. Revisa los README de cada modulo antes de ejecutar procesos masivos.
