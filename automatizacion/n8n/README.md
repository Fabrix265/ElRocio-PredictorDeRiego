# Copiloto agrónomo con n8n

Flujos de n8n sobre la API del sistema de riego:

| Flujo | Archivo | Qué hace |
|---|---|---|
| Avisos por Telegram | `flujos/avisos.json` | Cada hora (de 06:50 a 21:50) pide los **avisos** pendientes y los manda apenas pasan: el MDS cambia de nivel, falla la ingesta de datos o el suelo no responde al riego. No usa el modelo y nunca repite un aviso (ver [Avisos](#avisos-por-telegram)). |
| Informe diario | `flujos/informe_diario.json` | A las 06:15 (Lima) pide `/copiloto/resumen`, Claude redacta el informe y lo envía por Telegram. Las alertas de severidad alta se vuelven **sugerencias pendientes** en la app. |
| Agente de Telegram | `flujos/agente_telegram.json` | Responde preguntas por Telegram con datos reales (herramientas HTTP de solo lectura). Puede dejar sugerencias pendientes, nunca publicar ni cambiar el riego. |
| Chat de prueba | `flujos/agente_chat_prueba.json` | El mismo agente, para conversar desde el editor de n8n (botón **Open chat**) sin Telegram. Útil para probar y para la demo. |

Hay dos juegos con la misma lógica, según cómo llegas a Claude: `flujos/*.json` usa la API de Anthropic y
`flujos/devlum/*.json` usa **Devlum AI** (ver [Modelo](#modelo)). El de avisos no usa el modelo y sirve para los dos.

```text
Telegram ──▶ n8n (VPS, HTTPS) ──X-Token-Agente──▶ API /api/v1/copiloto/* ──▶ PostgreSQL
                │                                    (alertas calculadas en Python, con pruebas)
                └──▶ Claude (redacta y conversa; no calcula cifras)
```

El backend calcula los números y las alertas, y el LLM solo los redacta. Si Claude o n8n fallan, la app
funciona igual.

## 1. Backend

1. Aplica la migración `0007` (tablas `token_servicio` y `copiloto_sugerencia`) en la base que use la API:
   `alembic upgrade head` con `DATABASE_URL_MIGRACIONES`, igual que las anteriores.
2. Crea el token del agente. Se muestra **una sola vez** y en la BD solo queda su hash:

   ```bash
   cd backend
   .venv/Scripts/python -m app.cli crear-token-agente n8n-copiloto
   # o, para no verlo en pantalla (fuera del repo): ... crear-token-agente n8n-copiloto --archivo ~/token-agente.txt
   ```

   `listar-tokens-agente` muestra los tokens y su último uso; `revocar-token-agente n8n-copiloto` lo
   corta al instante.
3. Comprueba que responde (con tu dominio):

   ```bash
   curl -H "X-Token-Agente: <token>" https://<api>/api/v1/copiloto/resumen
   ```

El token solo sirve para `/copiloto/*`: leer el resumen, plan, agua, clima, pronóstico y sugerencias,
y crear sugerencias. No puede publicar, corregir, regenerar ni tocar el riego, y no ve usuarios. Cada
llamada queda en la auditoría como `consulta_agente`.

## 2. n8n en el VPS

Pon n8n **fuera del clon del repo**, para que `git pull` (o `riego-actualizar`) nunca lo toque:

```bash
mkdir -p /opt/n8n && cd /opt/n8n
cp /opt/riego/app/automatizacion/n8n/docker-compose.yml .
cp /opt/riego/app/automatizacion/n8n/.env.example .env
nano .env                 # N8N_DOMINIO y N8N_ENCRYPTION_KEY (openssl rand -hex 32)
docker compose up -d
```

n8n escucha solo en `127.0.0.1:5678`. Publícalo con HTTPS en tu proxy, por ejemplo con Caddy
(`/etc/caddy/Caddyfile`, y luego `systemctl reload caddy`):

```text
n8n.tu-dominio.pe {
    reverse_proxy 127.0.0.1:5678
}
```

Telegram necesita HTTPS para entregar los mensajes al webhook del flujo 2. Crea tu usuario de n8n
al abrirlo por primera vez y guarda la `N8N_ENCRYPTION_KEY` en un lugar seguro.

**`api_url`**: usa la dirección pública de la API (p. ej. `https://irrital.duckdns.org`). Si la API
escucha solo en `127.0.0.1:8000`, el contenedor de n8n no la alcanza por esa dirección, porque dentro
de Docker `127.0.0.1` es el propio contenedor.

Para actualizar n8n: cambia `N8N_VERSION` en `/opt/n8n/.env` y corre `docker compose pull && docker compose up -d`.
Los flujos y las credenciales quedan en el volumen `n8n_datos`.

## 3. Credenciales en n8n (Settings → Credentials)

| Nombre (como en los flujos) | Tipo | Valor |
|---|---|---|
| `Token agente copiloto` | Header Auth | Name: `X-Token-Agente` · Value: el token del paso 1 |
| `Bot Telegram copiloto` | Telegram API | El token que da @BotFather al crear el bot |
| `Anthropic copiloto` | Anthropic | La clave de la API de Claude (flujos de `flujos/`) |
| `Devlum AI` | OpenAI | API Key: tu clave `sk-dl-…` · Base URL: `https://ai.devlumlabs.com/api/v1` (flujos de `flujos/devlum/`) |

Las claves solo se guardan en n8n (cifradas). No van en los JSON ni en el repo.

## 4. Importar y configurar los flujos

1. **Workflows → Import from file**: importa los JSON de `flujos/` (o de `flujos/devlum/`) y `flujos/avisos.json`.
2. En cada nodo con credencial (HTTP, Telegram y Claude) elige la credencial del paso 3. Los JSON
   traen `REEMPLAZAR` como id.
3. Edita el nodo **Configuración** de cada flujo:
   - `api_url`: URL base de la API sin `/api/v1` (p. ej. `https://riego.tu-dominio.pe`).
   - `chat_ids` (informe) y `chat_ids_autorizados` (agente): IDs de chat de Telegram separados por coma.
   - `chat_ids_campo` y `chat_ids_sistema` (avisos): quién recibe los avisos de campo (MDS y riego) y los
     del sistema (ingesta de datos). Si `chat_ids_sistema` queda vacío, esos avisos van a los de campo.
4. Para saber el ID de chat de cada persona, activa el flujo del agente y pídele que escriba al bot.
   Si no está autorizado, el bot le responde con su ID. Agrégalo a la lista.
5. Activa los flujos. Para probar el informe sin esperar a las 06:15, o los avisos sin esperar a la
   siguiente hora, usa **Execute workflow**.

### Modelo

**Devlum AI.** Devlum expone los modelos de Claude con una API compatible con OpenAI. Por eso los
flujos de `flujos/devlum/` usan el nodo *OpenAI Chat Model* en la versión 1.2 (Chat Completions; la 1.3
usa por defecto la Responses API, que Devlum no documenta), con la URL base de Devlum y el modelo
`claude-opus-5-5`. Devlum lo lista con soporte de herramientas (`tools`), que el agente necesita. Ten en
cuenta que los datos pasan por un intermediario más (Devlum Digital SAC) antes de llegar al modelo, y que
su política no indica cuánto tiempo conservan los proveedores el texto de los mensajes.

**API de Anthropic.**

Los flujos usan **Claude Opus 5.5** (`claude-opus-5-5`) en el nodo *Anthropic Chat Model*.

- Si tu versión de n8n no lo lista, escríbelo en el campo de modelo como ID.
- No configures *Sampling Temperature*, *Top P* ni *Thinking/Budget* en el nodo: este modelo responde 400
  si se los envían. Si tu versión de n8n los manda igual, actualízala.
- El costo es de una llamada al día para el informe más una por pregunta en Telegram (cada
  respuesta del agente puede encadenar varias herramientas).

## Herramientas del agente

| Herramienta | Endpoint | Parámetros |
|---|---|---|
| `resumen_del_dia` | `GET /copiloto/resumen` | (hoy) |
| `plan_de_un_dia` | `GET /copiloto/plan` | `fecha` |
| `agua_del_modulo` | `GET /copiloto/agua` | `desde`, `hasta` |
| `agua_de_un_turno` | `GET /copiloto/agua` | `desde`, `hasta`, `turno` |
| `clima_y_planta` | `GET /copiloto/clima` | `desde`, `hasta` |
| `sugerencias_pendientes` | `GET /copiloto/sugerencias` | `estado=pendiente` |
| `crear_sugerencia` | `POST /copiloto/sugerencias` | `fecha`, `tipo`, `titulo`, `detalle`, `turno_codigo`, `alerta_codigo` |

Si algún nodo no se importa bien en tu versión de n8n, puedes rehacerlo a mano con esta tabla. Son
nodos *HTTP Request Tool* con la credencial `Token agente copiloto` y los parámetros llenados
con `$fromAI(...)`.

Comandos del bot (los resuelve el flujo; `/start`, `/ayuda` y `/avisos` no gastan el modelo): `/hoy`,
`/manana`, `/alertas`, `/semana`, `/turno TE03`, `/sugerencias`, `/avisos`, `/ayuda`.

## Avisos por Telegram

Los calcula el backend (`app/services/avisos_service.py`, con pruebas) en `GET /copiloto/avisos`, y el flujo
`avisos.json` los manda tal cual, sin el modelo:

| Código | A quién | Cuándo |
|---|---|---|
| `mds_nivel` | campo | El MDS del último día con dato cambió de nivel frente al día anterior: sube a estrés moderado (≥ 190 µm), alto (≥ 220) o crítico (≥ 250), o baja. |
| `ingesta_fallida` | sistema | 30 min después de `INGESTA_HORA`, una fuente de la ingesta programada de hoy falló, quedó incompleta o no corrió. También si corrió, pero el clima o Phytech no llegan a ayer, o el riego registrado tiene 2 o más días de atraso. |
| `riego_sin_respuesta` | campo | Se regó, pero la humedad de la zona radicular casi no subió: posible gotero tapado, válvula o fuga. Trae m³, m³/ha y ETo. |

Cada aviso tiene una clave (`código:módulo:fecha:detalle`). El flujo pide los pendientes
(`?pendientes=true`), arma un mensaje por chat, lo manda y confirma las claves con
`POST /copiloto/avisos/confirmar`, que queda en la auditoría como «Aviso del copiloto enviado por
Telegram». Un aviso confirmado no vuelve a salir. Si Telegram falla, no se confirma y sale en la
siguiente hora. Con `/avisos` el bot muestra los avisos de hoy (enviados o no), y la vista Copiloto de
la app también los muestra.

Los umbrales son los del semáforo de la app (`COPILOTO_MDS_*`). La espera tras la ingesta se cambia con
`COPILOTO_GRACIA_INGESTA_MIN`.

## Alertas que calcula el backend

| Código | Severidad | Cuándo |
|---|---|---|
| `plan_hoy_sin_generar` / `plan_hoy_sin_publicar` | alta | Hoy no hay cronograma, o sigue en borrador |
| `plan_manana_*` | info (media desde las 16:00) | Mañana sin generar o sin publicar |
| `*_correccion` | media | El subgerente pidió una corrección |
| `datos_atrasados` | media/alta | Riego, WeatherLink o Phytech no llegan a ayer (alta con 2+ días) |
| `desvio_plan_real` | media/alta | Un turno regó más de ±15 % de lo propuesto (alta con más de ±30 %) |
| `estres_mds` | media/alta | 2+ días seguidos con MDS ≥ 220 µm (alta si el último es ≥ 250 µm) |
| `estres_suelo` | media/alta | 2+ días con la zona radicular ≥ 0,5 % vol. bajo la línea de estrés |
| `riego_sin_respuesta` | alta | Se regó ≥ 10 m³/ha, pero la humedad radicular subió menos de ~35 % de lo normal |
| `humedad_sin_riego` | media | La humedad subió como un día de riego, sin riego registrado |
| `demanda_alta` | info | El pronóstico de Phytech trae ETo ≥ 1,2 × la media de la semana (y ≥ 4 mm) |

Los umbrales se cambian con las variables `COPILOTO_*` del backend (ver `backend/.env.example`).

## Cambiar los prompts

Los prompts están en `prompts/`. Después de editarlos, vuelve a generar los flujos y reimpórtalos:

```bash
python automatizacion/n8n/generar_flujos.py
```

## Cómo probarlo

Probado con **n8n 2.48.5** (fija esa versión en `N8N_VERSION` si no tienes otra razón). De lo más rápido a lo
más completo:

| Nivel | Comando | Qué comprueba |
|---|---|---|
| 1. Backend | `cd backend && .venv/Scripts/python -m pytest -q tests/test_copiloto.py` | Reglas de alertas, permisos, token, sugerencias (sin duplicados, también en paralelo) y que **cada herramienta de los JSON** responde como la llamaría n8n |
| 2. Lógica del bot | `node automatizacion/n8n/pruebas/probar_codigo.mjs` (para el juego Devlum: `FLUJOS_DIR=automatizacion/n8n/flujos/devlum` delante) | Los nodos Code: chats autorizados, comandos, `/ayuda`, alertas → sugerencias, destinatarios, aviso si el modelo falla y recorte al límite de Telegram |
| 3. n8n real (Docker) | `python automatizacion/n8n/pruebas/probar_n8n_local.py --token-archivo <ruta>` | Importa los flujos en n8n, ejecuta el informe contra la API (sin Claude ni Telegram) dos veces y el bot con 5 mensajes simulados |
| 4. Punta a punta | Con tus credenciales reales, en el VPS | Mensaje del informe en Telegram y respuestas del agente |

Para el nivel 3 necesitas la API corriendo (contra `riego_dev`), un token
(`python -m app.cli crear-token-agente n8n-local --archivo <ruta fuera del repo>`) y un n8n en Docker:

```bash
docker run -d --name n8n-copiloto-prueba -p 127.0.0.1:5679:5678   -e N8N_ENCRYPTION_KEY=$(openssl rand -hex 32) -e WEBHOOK_URL=http://localhost:5679/ -e GENERIC_TIMEZONE=America/Lima docker.n8n.io/n8nio/n8n:2.48.5
python automatizacion/n8n/pruebas/probar_n8n_local.py --token-archivo <ruta> --api-url http://host.docker.internal:8000
docker rm -f n8n-copiloto-prueba   # al terminar
```

Lista para el nivel 4 (una vez desplegado):

1. Escribe `/start` al bot desde un chat no autorizado. Debe responder con tu ID de chat. Agrégalo a
   `chat_ids_autorizados`.
2. `/start` de nuevo: la ayuda con los comandos, sin gastar el modelo.
3. `/hoy`: el plan por turno con m³, m³/ha y ETo. Compáralo con la pantalla Cronogramas.
4. «¿Por qué el TE02 tiene más agua hoy?»: debe citar ETo, MDS o humedad, sin inventar cifras.
5. «Publica el plan»: debe negarse y decir que se hace en la app.
6. En el flujo del informe, **Execute workflow**: llega el mensaje a los chats de `chat_ids`, y las
   alertas altas aparecen como sugerencias en la vista Copiloto. Ejecutarlo otra vez no las duplica.
7. Aprueba o descarta una sugerencia en la app y revisa la Auditoría (`consulta_agente`,
   `sugerencia_creada`, `sugerencia_aprobada`).

## Problemas comunes

- **401 en los nodos HTTP**: falta la credencial, el token está revocado, o el nombre de la cabecera no
  es exactamente `X-Token-Agente`.
- **422 «Indica modulo_id»**: hay más de un módulo activo. Agrega `modulo_id` a las consultas.
- **«Failed to receive response» en el chat de prueba**: n8n no sabe en qué puerto lo publicaste. Si no usas
  el 5678, define `WEBHOOK_URL` con la dirección real (p. ej. `http://localhost:5679/`).
- **El bot no responde**: el flujo del agente no está activo, o n8n no tiene HTTPS público (revisa
  `WEBHOOK_URL`).
- **El bot contesta «No pude consultar los datos en este momento»**: el agente falló (clave del modelo,
  saldo en Devlum, API caída o 401 del token). El detalle está en **Executions** del flujo. Si el modelo
  falla al redactar el informe diario, los chats reciben igual un aviso en vez de nada. Los mensajes se
  recortan a 4000 caracteres porque Telegram rechaza los de más de 4096.
- **400 del modelo**: quita la temperatura y el thinking del nodo de Claude (ver *Modelo*).
