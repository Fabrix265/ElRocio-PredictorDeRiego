# Backend

API FastAPI del sistema de prediccion de riego.

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuracion

Copia `backend/.env.example` a `backend/.env` y ajusta los valores si hace falta. El archivo `.env` no se versiona.

Variables disponibles:

- `APP_NAME`
- `APP_ENV`
- `DEBUG`
- `API_V1_PREFIX`
- `CORS_ORIGINS`

## Ejecucion

```powershell
uvicorn app.main:app --reload
```

Endpoints iniciales:

- `GET /`
- `GET /api/v1/health`

La documentacion interactiva queda en `http://localhost:8000/docs`.
