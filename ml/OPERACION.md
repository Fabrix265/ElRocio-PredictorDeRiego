# Guía de operación – Prueba del plan de riego en el entorno real

Esta guía explica cómo usar el sistema durante el **piloto en modo sombra**: el modelo
sugiere el plan de cada día, el operador sigue decidiendo y se compara lo sugerido con lo
que realmente se regó. Para el detalle técnico del pipeline ver [README.md](README.md).

## Estado actual (nov-2026)

| Qué | Estado |
|---|---|
| Modelo actual | `models/plan_riego/actual/` – versión `2026-11-07_1031`, datos abr-2021 a 04/11/2026 |
| N° de ciclos | ✅ Usable · acierta ~81 % de los días (97 % con ±1 ciclo) |
| m3/ha por ciclo | ✅ Usable como sugerencia · error típico ±3 m3/ha |
| Duración por ciclo | ✅ Usable · error típico ±9 min (usa el caudal de los últimos 30 días) |
| Hora de inicio y fin | ⚠️ Solo orientativa · error típico ±2 h; no programar el controlador con estos horarios |
| Rangos (p10–p90) | ✅ Usables para saber cuándo desconfiar · cubren ~75 % de los casos (meta 80 %) |
| Ejecución | Manual (comandos de esta guía); no hay tarea programada ni conexión con el backend |

**Conclusión: listo para el piloto en modo sombra, no para producción automática.**

## 1. Preparación (una sola vez)

Desde la raíz del repositorio, en PowerShell:

```powershell
python -m venv ml/.venv
ml\.venv\Scripts\Activate.ps1
pip install -r ml/requirements.txt
python -m pytest ml/tests -q          # debe terminar en "passed"
```

Credenciales de las APIs (solo para descargar datos):

```powershell
$env:PHYTECH_API_KEY="..."
$env:PHYTECH_API_SECRET="..."
$env:WEATHERLINK_API_KEY="..."
$env:WEATHERLINK_API_SECRET="..."
```

## 2. Fuentes de datos

| Fuente | Archivo que lee el pipeline | Cómo se actualiza |
|---|---|---|
| Riego (base) | `ml/data/raw/data_riego_historico.xlsx`, hoja `MOD5` | Reemplazar el Excel por la versión nueva que envían (mismas columnas) |
| Meteorología | `ml/data/raw/data_metereologica.xlsx` | Reemplazar por el export nuevo (mismo formato). La API de WeatherLink ya descarga datos a `data/raw/WeatherLink/`, pero el pipeline todavía no los lee |
| Phytech (suelo, planta, NDVI) | `ml/data/raw/data_phytech.xlsx` (se genera) | `descargar_phytech.py` (API) + `limpiar_phytech.py` |

La ruta de cada archivo se cambia en [`config/pipeline.yaml`](config/pipeline.yaml), sección `rutas`.

**Regla clave:** para planificar el día D, las tres fuentes deben llegar **hasta el día D-1**.
Si alguna no está al día, `predecir.py` lo avisa con un `WARNING` y el plan sale igual pero
con menos precisión.

## 3. Rutina diaria (antes de que empiece el día)

```powershell
# 1) Actualizar fuentes
#    - copiar el data_riego_historico.xlsx nuevo a ml/data/raw/
#    - copiar el data_metereologica.xlsx nuevo a ml/data/raw/
python ml/src/riego_ml/data_extraction/descargar_phytech.py
python ml/src/riego_ml/pipelines/limpiar_phytech.py

# 2) Unir los datos (no reentrena)
python ml/src/riego_ml/pipelines/unir_datos.py

# 3) Plan del día siguiente al último riego registrado (o --fecha AAAA-MM-DD)
python ml/src/riego_ml/pipelines/predecir.py
```

Salida: `ml/reports/predicciones/plan_riego_<fecha>.xlsx`

| Hoja | Contenido |
|---|---|
| `Plan_por_turno` | 1 fila por turno: n° de ciclos, totales y, por ciclo, m3/ha (con rango), duración, hora de inicio (con rango) y fin |
| `Plan_por_ciclo` | 1 fila por ciclo con todos los campos, m3 y rangos |

Cómo usarlo: entregar el plan al operador como **sugerencia**. Si el rango de un valor es
muy ancho (ej. m3/ha entre 13 y 30), es un día incierto: decidir con el criterio habitual.

## 4. Rutina semanal: medir el piloto

Cuando llega el registro real de riego de la semana:

```powershell
python ml/src/riego_ml/pipelines/unir_datos.py
python ml/src/riego_ml/pipelines/preparar_dataset.py --sin-excel
python ml/src/riego_ml/pipelines/evaluar_modelo.py --desde 2026-11-05
```

`--desde` es el primer día del piloto (después del último dato con que se entrenó el modelo
actual, para que la medición sea honesta). El resultado queda en
`ml/reports/evaluaciones/evaluacion_<desde>_fin.xlsx` con las mismas métricas del
entrenamiento.

Criterios propuestos para dar el piloto por bueno (2–4 semanas):

| Métrica | Meta |
|---|---|
| N° de ciclos: acierto | ≥ 80 % |
| m3/ha por ciclo: MAE | ≤ 3,5 m3/ha |
| Duración por ciclo: MAE | ≤ 10 min |
| Rango m3/ha: cobertura | ≥ 70 % |
| Hora de inicio | Solo seguimiento (todavía no es meta) |

## 5. Rutina mensual: reentrenar

```powershell
python ml/src/riego_ml/pipelines/ejecutar_todo.py
```

- Crea una nueva versión en `models/plan_riego/versiones/<fecha>/` y la copia a `actual/`.
- Agrega una fila a `ml/reports/historial_entrenamientos.xlsx` para comparar con las anteriores.
- Para comparar la versión nueva con la anterior en el mismo período:

```powershell
python ml/src/riego_ml/pipelines/evaluar_modelo.py --desde <fecha> `
  --modelos ml/models/plan_riego/versiones/<version_anterior> --reentrenar-hasta <fecha - 7 días>
```

**Volver a una versión anterior:** copiar `modelo_plan_riego.joblib` y `metadata.json` de
`models/plan_riego/versiones/<version>/` a `models/plan_riego/actual/`.

## 6. Problemas frecuentes

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `WARNING Faltan datos de ...` al predecir | Alguna fuente no llega hasta ayer | Actualizar esa fuente y correr `unir_datos.py` |
| `Faltan columnas en ... [MOD5]` | El Excel de riego cambió de formato | Revisar nombres de columnas/hoja; la ruta y la hoja se configuran en `pipeline.yaml` |
| `No existe el modelo ...` | No se entrenó todavía | Correr `ejecutar_todo.py` |
| `ModuleNotFoundError` | Entorno sin dependencias | `pip install -r ml/requirements.txt` dentro del venv |
| El plan repite siempre el mismo n° de ciclos | Es el comportamiento esperado: el modelo repite lo de ayer salvo un cambio muy probable | Normal; el cambio se detecta al día siguiente |

## 7. Qué falta para producción

- [ ] Recibir el registro de riego **todos los días** (hoy llega por Excel, sin frecuencia fija).
- [ ] Conectar la meteorología a la API de WeatherLink (adaptar unidades y estación de ENSUEÑO 1).
- [ ] Tarea programada diaria (descarga + unir + predecir).
- [ ] Conectar `predecir` al backend (`backend/app/ml/` está preparado pero vacío) y mostrarlo en el frontend.
- [ ] Mejorar la hora de inicio (modelar el arranque del módulo y la secuencia de turnos).
- [ ] Usar el programa de riego semanal como dato de entrada cuando haya más semanas registradas.
