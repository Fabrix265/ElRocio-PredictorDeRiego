# Despliegue gratuito: Vercel (frontend) + Render (API)

```
Navegador ──https──▶ <proyecto>.vercel.app          (React, archivos estáticos)
                     <proyecto>.vercel.app/api/*  ──https──▶ riego-el-rocio-api.onrender.com (FastAPI)
                                                                     │
                                                                     └──▶ Supabase (PostgreSQL)
```

El navegador solo habla con Vercel. Vercel reenvía `/api/*` a Render (`frontend/vercel.json`), así que
la API queda en el **mismo sitio** que el frontend: la cookie de sesión `SameSite=strict` funciona, no
hace falta CORS y `VITE_API_URL` se deja vacío.

| Archivo | Para qué |
|---|---|
| `render.yaml` | Define el servicio de Render (plan Free, build, arranque, health check, variables). |
| `deploy/render/descargar_modelo.py` | En el build descarga el `.joblib` desde `MODELO_URL` y verifica su sha256. |
| `frontend/vercel.json` | Reenvío de `/api/*` a Render, rutas de la SPA y cabeceras de seguridad. |
| `.github/workflows/mantener-api-despierta.yml` | Ping cada 10 min para que Render Free no duerma la API. |

## Pasos (una sola vez)

### 0. Subir estos archivos a GitHub
Render y Vercel leen el repo de GitHub: estos archivos tienen que estar en la rama que se despliega
(`main` en `render.yaml`). Haz commit, push y merge a `main` como siempre.

### 1. Subir el modelo a un lugar privado
El modelo no está en git (H10) y el repo es público, así que **no** lo subas al repo ni a un Release
público. Lo más simple: Supabase → **Storage** → crear un bucket **privado** (por ejemplo `modelos`) →
subir `ml/models/plan_riego/actual/modelo_plan_riego.joblib` → en el archivo, **Get URL** con una
expiración larga (por ejemplo 1 año). Esa URL firmada es `MODELO_URL` (trátala como secreto).

sha256 del modelo actual (`ML_MODEL_SHA256`):
`446b934de93d9eabc42ca9943dfbd4b56e39e625fb099ee74d15d5f772e5a9a4`
Si reentrenas, recalcúlalo (`certutil -hashfile modelo_plan_riego.joblib SHA256`) y actualiza las dos
variables.

### 2. Migraciones en Supabase
Render **no** corre migraciones. Si hay migraciones nuevas, aplícalas tú antes del despliegue
(`alembic upgrade head` con `DATABASE_URL_MIGRACIONES`). `/api/v1/health` muestra
`"migraciones": "pendientes"` si falta alguna.

### 3. Render
1. Render → **New → Blueprint** → elegir el repo. Render lee `render.yaml`.
2. Te pedirá las variables marcadas `sync: false`:

   | Variable | Valor |
   |---|---|
   | `FRONTEND_URL` | `https://<proyecto>.vercel.app` (la URL de producción de Vercel; si aún no la tienes, pon una provisional y corrígela después del paso 4) |
   | `DATABASE_URL` | La del **pooler 6543 con el rol `riego_app`** (no la del dueño: la API se niega a arrancar con un rol inseguro) |
   | `JWT_SECRET` | Al menos 32 caracteres aleatorios (no reutilices el de desarrollo) |
   | `ML_MODEL_SHA256` | El del paso 1 |
   | `MODELO_URL` | La URL firmada del paso 1 |
   | `SMTP_*`, `PHYTECH_*`, `WEATHERLINK_*` | Los mismos de tu `.env` de producción; los que no uses, déjalos vacíos |

3. Crear. El primer build tarda varios minutos (instala pandas, xgboost, lightgbm, catboost).
4. Comprueba `https://riego-el-rocio-api.onrender.com/api/v1/health` → `"bd": "ok"`, `"rol_bd": "ok"`.

Si Render te asigna otro nombre (por ejemplo `riego-el-rocio-api-x1y2.onrender.com`), cámbialo en
`frontend/vercel.json` y en `.github/workflows/mantener-api-despierta.yml`.

### 4. Vercel
1. **Add New → Project** → importar el repo.
2. **Root Directory**: `frontend`. Framework: Vite (lo detecta solo). No hace falta ninguna variable
   (`VITE_API_URL` vacío).
3. Deploy. La URL de producción (`https://<proyecto>.vercel.app`) es la que va en `FRONTEND_URL` de
   Render; si cambió, actualízala en Render (se redespliega solo).

### 5. Mantenerla despierta
El workflow de GitHub Actions empieza a correr solo cuando está en la rama por defecto. Puedes probarlo en
**Actions → Mantener API despierta → Run workflow**.

## Día a día
- **Actualizar**: push a `main` → Render y Vercel redespliegan solos.
- **Logs**: Render → el servicio → *Logs*.
- **Primer admin**: `python -m app.cli crear-admin` se corre desde tu PC contra Supabase (Render Free
  no tiene consola).

## Límites del plan Free (conocidos)
- 512 MB de RAM: el backend con el modelo cargado usa ~330 MB. Un solo worker (`python -m app`).
- 0,1 CPU: generar cronogramas es más lento que en local.
- Si la API duerme (el ping falló), la primera petición tarda ~1 min.
- Solo la URL de **producción** de Vercel puede iniciar sesión: las URL de *preview* tienen otro
  `Origin` y el backend las rechaza.
- La IP real del cliente llega en `X-Forwarded-For` (`TRUSTED_PROXIES=*`). Quien llame directo a
  `onrender.com` saltándose Vercel podría falsearla; solo afecta al límite de intentos por IP y a la IP
  de la auditoría.
