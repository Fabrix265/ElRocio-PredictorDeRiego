"""Genera los flujos importables de n8n a partir de los prompts de ``prompts/``.

Dos juegos con la misma lógica, según dónde se llama a Claude:

- ``flujos/*.json``: API de Anthropic (nodo *Anthropic Chat Model*, credencial «Anthropic copiloto»).
- ``flujos/devlum/*.json``: Devlum AI, API compatible con OpenAI (nodo *OpenAI Chat Model* con la URL
  base de Devlum, credencial «Devlum AI»).

Cada juego trae el informe diario, el agente de Telegram y un chat de prueba (el mismo agente, para
conversar desde el editor de n8n sin Telegram).

Los prompts son la fuente: si cambias uno, vuelve a correr ``python generar_flujos.py`` y reimporta el
flujo en n8n. No lleva claves: las credenciales se eligen en n8n al importar (ver README.md).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
MODELO = "claude-opus-5-5"
API_URL_EJEMPLO = "https://riego.tu-dominio.pe"
CRED_TOKEN = {"httpHeaderAuth": {"id": "REEMPLAZAR", "name": "Token agente copiloto"}}
CRED_TELEGRAM = {"telegramApi": {"id": "REEMPLAZAR", "name": "Bot Telegram copiloto"}}
CRED_ANTHROPIC = {"anthropicApi": {"id": "REEMPLAZAR", "name": "Anthropic copiloto"}}
CRED_DEVLUM = {"openAiApi": {"id": "REEMPLAZAR", "name": "Devlum AI"}}
DEVLUM_URL = "https://ai.devlumlabs.com/api/v1"
PROVEEDORES = ("anthropic", "devlum")
CONFIG = "Configuración"
_proveedor = "anthropic"  # lo fija main() para cada juego de flujos
DISPARADORES_WEBHOOK = {"n8n-nodes-base.telegramTrigger", "@n8n/n8n-nodes-langchain.chatTrigger"}


def _id(nombre: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"riego-el-rocio/n8n/{nombre}"))


def nodo(nombre: str, tipo: str, version: float, posicion: tuple[int, int], parametros: dict[str, Any],
         credenciales: dict[str, Any] | None = None) -> dict[str, Any]:
    salida = {"parameters": parametros, "id": _id(nombre), "name": nombre, "type": tipo, "typeVersion": version,
              "position": list(posicion)}
    if tipo in DISPARADORES_WEBHOOK:
        # Sin webhookId, n8n arma la ruta con el nombre del nodo (con espacios) y no la registra al
        # publicar: Telegram recibe 404. El editor lo asigna solo; en un JSON importado debe venir.
        salida["webhookId"] = _id(f"webhook-{nombre}")
    if credenciales:
        salida["credentials"] = credenciales
    return salida


def asignaciones(valores: list[tuple[str, Any, str]]) -> dict[str, Any]:
    return {"assignments": {"assignments": [
        {"id": _id(f"asig-{n}"), "name": n, "value": v, "type": t} for n, v, t in valores
    ]}, "options": {}}


def url(ruta: str) -> str:
    return f"={{{{ $('{CONFIG}').first().json.api_url }}}}/api/v1{ruta}"


def claude(nombre: str, posicion: tuple[int, int]) -> dict[str, Any]:
    # Sin temperatura ni «thinking» explícitos: Claude Opus 5.5 los rechaza (ver README).
    if _proveedor == "devlum":
        # v1.2 usa Chat Completions (la v1.3 usa por defecto la Responses API, que Devlum no tiene).
        return nodo(nombre, "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2, posicion, {
            "model": {"__rl": True, "value": MODELO, "mode": "id"},
            "options": {"baseURL": DEVLUM_URL, "maxTokens": 4000},
        }, CRED_DEVLUM)
    return nodo(nombre, "@n8n/n8n-nodes-langchain.lmChatAnthropic", 1.3, posicion, {
        "model": {"__rl": True, "value": MODELO, "mode": "id"},
        "options": {"maxTokensToSample": 4000},
    }, CRED_ANTHROPIC)


def telegram(nombre: str, posicion: tuple[int, int], chat: str, texto: str) -> dict[str, Any]:
    return nodo(nombre, "n8n-nodes-base.telegram", 1.2, posicion, {
        "chatId": chat, "text": texto, "additionalFields": {"appendAttribution": False},
    }, CRED_TELEGRAM)


def conexion(destino: str, tipo: str = "main", indice: int = 0) -> dict[str, Any]:
    return {"node": destino, "type": tipo, "index": indice}


def flujo(nombre: str, nodos: list[dict[str, Any]], conexiones: dict[str, Any]) -> dict[str, Any]:
    return {"name": nombre, "nodes": nodos, "connections": conexiones, "active": False,
            "settings": {"executionOrder": "v1", "timezone": "America/Lima", "saveDataSuccessExecution": "all"},
            "pinData": {}, "meta": {"templateCredsSetupCompleted": False}, "tags": []}


# --- Flujo 1: informe diario ------------------------------------------------------

SUGERENCIAS_JS = """// Alertas de severidad alta -> sugerencias pendientes (el backend no duplica las iguales).
const r = $input.first().json;
const TIPO = {
  riego_sin_respuesta: 'revisar_equipo',
  humedad_sin_riego: 'revisar_datos',
  datos_atrasados: 'revisar_datos',
  desvio_plan_real: 'ajustar_riego',
  estres_mds: 'ajustar_riego',
  estres_suelo: 'ajustar_riego',
  plan_hoy_sin_generar: 'regenerar_plan',
};
return (r.alertas || [])
  .filter((a) => a.severidad === 'alta' && TIPO[a.codigo])
  .map((a) => ({ json: {
    modulo_id: r.modulo.id,
    fecha: a.fecha || r.fecha,
    turno_codigo: a.turno_codigo || null,
    tipo: TIPO[a.codigo],
    alerta_codigo: a.codigo,
    titulo: String(a.titulo).slice(0, 160),
    detalle: String(a.detalle).slice(0, 2000),
  } }));"""

LIMITE_TELEGRAM = 4000  # Telegram rechaza los mensajes de más de 4096 caracteres

INFORME_FALLIDO = ("No pude redactar el informe de hoy. Revisa el plan y las alertas en la vista Copiloto "
                   "de la app.")

DESTINATARIOS_JS = f"""// Un ítem por chat de Telegram de la lista de Configuración (texto recortado al límite de Telegram).
// Si el modelo falló, «Redactar informe» sigue sin texto y se manda un aviso en su lugar.
const ids = String($('{CONFIG}').first().json.chat_ids || '')
  .split(',').map((s) => s.trim()).filter(Boolean);
const texto = (String($input.first().json.text || '').trim() || '{INFORME_FALLIDO}').slice(0, {LIMITE_TELEGRAM});
return ids.map((chat_id) => ({{ json: {{ chat_id, texto }} }}));"""

# Si el agente falla (modelo caído, API sin respuesta, demasiadas herramientas), el bot avisa en vez de callar.
SIN_RESPUESTA = ("No pude consultar los datos en este momento. Intenta de nuevo en unos minutos o revisa "
                 "el plan en la app.")
RESPUESTA_AGENTE = f"={{{{ String($json.output || '{SIN_RESPUESTA}').slice(0, {LIMITE_TELEGRAM}) }}}}"


def informe_diario() -> dict[str, Any]:
    prompt = (AQUI / "prompts" / "informe_diario.md").read_text(encoding="utf-8").rstrip()
    nodos = [
        nodo("Cada día 06:15", "n8n-nodes-base.scheduleTrigger", 1.2, (0, 0),
             {"rule": {"interval": [{"field": "cronExpression", "expression": "15 6 * * *"}]}}),
        nodo(CONFIG, "n8n-nodes-base.set", 3.4, (220, 0), asignaciones([
            ("api_url", API_URL_EJEMPLO, "string"),
            ("chat_ids", "ID_CHAT_ENCARGADO,ID_CHAT_SUBGERENTE", "string"),
        ])),
        nodo("Resumen del copiloto", "n8n-nodes-base.httpRequest", 4.2, (440, 0), {
            "url": url("/copiloto/resumen"), "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth", "options": {"timeout": 60000},
        }, CRED_TOKEN),
        nodo("Redactar informe", "@n8n/n8n-nodes-langchain.chainLlm", 1.5, (680, -100), {
            "promptType": "define", "text": "=" + prompt + "\n{{ JSON.stringify($json) }}",
        }),
        claude("Claude", (680, 120)),
        nodo("Destinatarios", "n8n-nodes-base.code", 2, (920, -100), {"jsCode": DESTINATARIOS_JS}),
        telegram("Enviar por Telegram", (1140, -100), "={{ $json.chat_id }}", "={{ $json.texto }}"),
        nodo("Sugerencias desde alertas", "n8n-nodes-base.code", 2, (680, 260), {"jsCode": SUGERENCIAS_JS}),
        nodo("Crear sugerencia", "n8n-nodes-base.httpRequest", 4.2, (920, 260), {
            "method": "POST", "url": url("/copiloto/sugerencias"), "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth", "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json) }}", "options": {},
        }, CRED_TOKEN),
    ]
    next(n for n in nodos if n["name"] == "Redactar informe")["onError"] = "continueRegularOutput"
    conexiones = {
        "Cada día 06:15": {"main": [[conexion(CONFIG)]]},
        CONFIG: {"main": [[conexion("Resumen del copiloto")]]},
        "Resumen del copiloto": {"main": [[conexion("Redactar informe"), conexion("Sugerencias desde alertas")]]},
        "Claude": {"ai_languageModel": [[conexion("Redactar informe", "ai_languageModel")]]},
        "Redactar informe": {"main": [[conexion("Destinatarios")]]},
        "Destinatarios": {"main": [[conexion("Enviar por Telegram")]]},
        "Sugerencias desde alertas": {"main": [[conexion("Crear sugerencia")]]},
    }
    return flujo("Copiloto · informe diario", nodos, conexiones)


# --- Flujo 2: agente conversacional por Telegram ------------------------------------

PREPARAR_JS = f"""// Autoriza el chat, atiende /start, /ayuda y /avisos sin gastar el modelo y traduce los comandos.
const msg = $('Mensaje de Telegram').first().json.message || {{}};
const cfg = $('{CONFIG}').first().json;
const autorizados = String(cfg.chat_ids_autorizados || '').split(',').map((s) => s.trim()).filter(Boolean);
const chat_id = String(msg.chat?.id ?? '');
const texto = String(msg.text || '').trim().slice(0, 1000);
const COMANDOS = {{
  '/hoy': 'Dame el plan de riego de hoy por turno, con m³, m³/ha y la ETo.',
  '/manana': 'Dame el plan de riego de mañana por turno, con m³, m³/ha y la ETo.',
  '/alertas': '¿Qué alertas hay hoy y qué conviene revisar?',
  '/semana': '¿Cuánta agua regamos en los últimos 7 días frente a lo propuesto, por turno?',
  '/sugerencias': '¿Qué sugerencias están pendientes de aprobación?',
}};
let tipo = 'agente';
let pregunta = texto;
if (!autorizados.includes(chat_id)) tipo = 'no_autorizado';
else if (!texto) tipo = 'sin_texto';
else if (/^\\/(start|ayuda)\\b/i.test(texto)) tipo = 'ayuda';
else {{
  const partes = texto.split(/\\s+/);
  const comando = partes[0].split('@')[0].toLowerCase();
  if (comando === '/avisos') tipo = 'avisos';
  else if (COMANDOS[comando]) pregunta = COMANDOS[comando];
  else if (comando === '/turno') pregunta = `Dame el plan de hoy del turno ${{partes[1] || ''}} y su agua de los últimos 7 días.`;
}}
return [{{ json: {{ tipo, chat_id, pregunta }} }}];"""

AYUDA = (
    "Hola, soy el copiloto de riego del MOD5. Te respondo con los datos del sistema.\\n\\n"
    "Comandos:\\n"
    "• /hoy – plan de hoy por turno\\n"
    "• /manana – plan de mañana\\n"
    "• /alertas – alertas del día\\n"
    "• /semana – agua de los últimos 7 días\\n"
    "• /turno TE03 – detalle de un turno\\n"
    "• /sugerencias – pendientes de aprobación\\n"
    "• /avisos – avisos del día (MDS, ingesta de datos, riego)\\n\\n"
    "También puedes preguntar libre, por ejemplo:\\n"
    "• ¿Por qué el TE02 tiene más agua hoy?\\n"
    "• ¿Hubo estrés esta semana?\\n"
    "• ¿Qué ETo se espera el jueves?"
)

AVISOS_BOT_JS = f"""// /avisos: los avisos de hoy (ya enviados o pendientes), sin gastar el modelo.
const r = $input.first().json;
const chat_id = $('Preparar').first().json.chat_id;
let texto;
if (r.error || !Array.isArray(r.avisos)) {{
  texto = 'No pude consultar los avisos en este momento. Intenta de nuevo en unos minutos.';
}} else if (!r.avisos.length) {{
  texto = 'No hay avisos por ahora. Te escribo apenas el MDS cambie de nivel, falle la ingesta de datos o el suelo no responda al riego.';
}} else {{
  texto = ['Avisos de hoy:', ...r.avisos.map((a) => `${{a.icono}} ${{a.titulo}}${{a.enviado ? ' (ya avisado)' : ''}}\\n${{a.detalle}}`)].join('\\n\\n');
}}
return [{{ json: {{ chat_id, texto: texto.slice(0, {LIMITE_TELEGRAM}) }} }}];"""

HOY = "{{ $now.setZone('America/Lima').toFormat('cccc d \\'de\\' LLLL \\'de\\' yyyy', { locale: 'es' }) }}"
HOY_ISO = "{{ $now.setZone('America/Lima').toISODate() }}"


def herramienta(nombre: str, posicion: tuple[int, int], descripcion: str, ruta: str,
                query: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    parametros: dict[str, Any] = {
        "toolDescription": descripcion, "method": "GET", "url": url(ruta),
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "options": {},
    }
    if query:
        parametros["sendQuery"] = True
        parametros["queryParameters"] = {"parameters": [
            {"name": n, "value": f"={{{{ $fromAI('{n}', `{d}`, 'string') }}}}"} for n, d in query
        ]}
    return nodo(nombre, "n8n-nodes-base.httpRequestTool", 4.2, posicion, parametros, CRED_TOKEN)


def crear_sugerencia(posicion: tuple[int, int]) -> dict[str, Any]:
    campos = [
        ("fecha", "Día al que se refiere, AAAA-MM-DD"),
        ("tipo", "Uno de: revisar_equipo, revisar_datos, regenerar_plan, ajustar_riego, otro"),
        ("titulo", "Acción concreta en menos de 160 caracteres, p. ej. Revisar la válvula del TE03"),
        ("detalle", "Por qué: cifras y alerta que la respaldan (máx. 2000 caracteres)"),
        ("turno_codigo", "Turno (TE01 a TE05) o vacío si es de todo el módulo"),
        ("alerta_codigo", "Código de la alerta del resumen que la origina, o vacío"),
    ]
    return nodo("crear_sugerencia", "n8n-nodes-base.httpRequestTool", 4.2, posicion, {
        "toolDescription": (
            "Deja una sugerencia PENDIENTE para que el encargado la apruebe o descarte en la app. No cambia "
            "el plan ni el riego. Úsala solo con una alerta o dato concreto que la respalde."
        ),
        "method": "POST", "url": url("/copiloto/sugerencias"), "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth", "sendBody": True, "specifyBody": "keypair",
        "bodyParameters": {"parameters": [
            {"name": n, "value": f"={{{{ $fromAI('{n}', `{d}`, 'string') }}}}"} for n, d in campos
        ]},
        "options": {},
    }, CRED_TOKEN)


def _herramientas() -> list[dict[str, Any]]:
    fechas = "Fecha AAAA-MM-DD"
    herramientas = [
        herramienta("resumen_del_dia", (760, 420),
                    "Resumen de HOY ya calculado: plan de hoy y mañana por turno (m³, m³/ha, horario, ETo), agua de "
                    "ayer, clima y MDS de los últimos días, pronóstico y alertas. Úsala primero para casi todo.",
                    "/copiloto/resumen"),
        herramienta("plan_de_un_dia", (900, 420),
                    "Plan de riego de un día por turno: ciclos, horario, m³ y m³/ha, ETo y estado (borrador o "
                    "publicado). Devuelve null si ese día no tiene cronograma.",
                    "/copiloto/plan", [("fecha", fechas)]),
        herramienta("agua_del_modulo", (1040, 420),
                    "Agua aplicada frente a la propuesta por día y turno, con totales en m³ y m³/ha. Rango máx. 92 días.",
                    "/copiloto/agua", [("desde", fechas), ("hasta", fechas)]),
        herramienta("agua_de_un_turno", (1180, 420),
                    "Como agua_del_modulo pero solo para un turno (TE01 a TE05).",
                    "/copiloto/agua", [("desde", fechas), ("hasta", fechas), ("turno", "Código del turno, p. ej. TE03")]),
        herramienta("clima_y_planta", (1320, 420),
                    "Por día: ETo, temperatura, humedad relativa, lluvia, MDS con su nivel de estrés, humedad de la "
                    "zona radicular y línea de estrés, NDVI; más el pronóstico. Rango máx. 31 días.",
                    "/copiloto/clima", [("desde", fechas), ("hasta", fechas)]),
        herramienta("sugerencias_pendientes", (1460, 420),
                    "Sugerencias del copiloto que esperan aprobación del encargado.",
                    "/copiloto/sugerencias", [("estado", "Siempre: pendiente")]),
        crear_sugerencia((1600, 420)),
    ]
    return herramientas


def _agente(texto: str, sesion: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Nodo del agente con su modelo, memoria y herramientas, y las conexiones de esos sub-nodos."""
    sistema = (AQUI / "prompts" / "sistema_agente.md").read_text(encoding="utf-8").rstrip()
    herramientas = _herramientas()
    nodos = [
        nodo("Agente copiloto", "@n8n/n8n-nodes-langchain.agent", 1.7, (920, -120), {
            "promptType": "define",
            "text": f"=Hoy es {HOY} ({HOY_ISO}), hora de Lima.\n\n{texto}",
            "options": {"systemMessage": sistema, "maxIterations": 8},
        }),
        claude("Claude", (620, 420)),
        nodo("Memoria del chat", "@n8n/n8n-nodes-langchain.memoryBufferWindow", 1.3, (480, 420), {
            "sessionIdType": "customKey", "sessionKey": sesion, "contextWindowLength": 10,
        }),
        *herramientas,
    ]
    conexiones: dict[str, Any] = {
        "Claude": {"ai_languageModel": [[conexion("Agente copiloto", "ai_languageModel")]]},
        "Memoria del chat": {"ai_memory": [[conexion("Agente copiloto", "ai_memory")]]},
    }
    for h in herramientas:
        conexiones[h["name"]] = {"ai_tool": [[conexion("Agente copiloto", "ai_tool")]]}
    return nodos, conexiones


def agente_telegram() -> dict[str, Any]:
    nodos_agente, conexiones_agente = _agente("{{ $json.pregunta }}", "={{ $('Preparar').first().json.chat_id }}")
    nodos_agente[0]["onError"] = "continueRegularOutput"
    nodos = [
        nodo("Mensaje de Telegram", "n8n-nodes-base.telegramTrigger", 1.1, (0, 0),
             {"updates": ["message"], "additionalFields": {}}, CRED_TELEGRAM),
        nodo(CONFIG, "n8n-nodes-base.set", 3.4, (220, 0), asignaciones([
            ("api_url", API_URL_EJEMPLO, "string"),
            ("chat_ids_autorizados", "ID_CHAT_ENCARGADO,ID_CHAT_SUBGERENTE", "string"),
        ])),
        nodo("Preparar", "n8n-nodes-base.code", 2, (440, 0), {"jsCode": PREPARAR_JS}),
        nodo("¿Qué hacer?", "n8n-nodes-base.switch", 3.2, (660, 0), {
            "rules": {"values": [
                {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                                "conditions": [{"id": _id(f"cond-{t}"), "leftValue": "={{ $json.tipo }}", "rightValue": t,
                                                "operator": {"type": "string", "operation": "equals"}}],
                                "combinator": "and"},
                 "renameOutput": True, "outputKey": t}
                for t in ("agente", "ayuda", "sin_texto", "no_autorizado", "avisos")
            ]},
            "options": {},
        }),
        *nodos_agente,  # el agente sigue con un ítem {error} si falla: «Responder» manda el aviso
        telegram("Responder", (1220, -120), "={{ $('Preparar').first().json.chat_id }}", RESPUESTA_AGENTE),
        telegram("Ayuda", (920, 60), "={{ $json.chat_id }}", AYUDA.replace("\\n", "\n")),
        telegram("Solo texto", (920, 200), "={{ $json.chat_id }}",
                 "Por ahora solo leo mensajes de texto. Escríbeme tu pregunta o usa /ayuda."),
        telegram("No autorizado", (920, 340), "={{ $json.chat_id }}",
                 "=Este chat no está autorizado. Pídele al administrador que agregue tu ID de chat: "
                 "{{ $json.chat_id }}"),
        {**nodo("Avisos de hoy", "n8n-nodes-base.httpRequest", 4.2, (920, 480), {
            "url": url("/copiloto/avisos"), "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth", "options": {"timeout": 60000},
        }, CRED_TOKEN), "onError": "continueRegularOutput"},
        nodo("Formatear avisos", "n8n-nodes-base.code", 2, (1140, 480), {"jsCode": AVISOS_BOT_JS}),
        telegram("Responder avisos", (1360, 480), "={{ $json.chat_id }}", "={{ $json.texto }}"),
    ]
    conexiones: dict[str, Any] = {
        "Mensaje de Telegram": {"main": [[conexion(CONFIG)]]},
        CONFIG: {"main": [[conexion("Preparar")]]},
        "Preparar": {"main": [[conexion("¿Qué hacer?")]]},
        "¿Qué hacer?": {"main": [[conexion("Agente copiloto")], [conexion("Ayuda")], [conexion("Solo texto")],
                                 [conexion("No autorizado")], [conexion("Avisos de hoy")]]},
        "Agente copiloto": {"main": [[conexion("Responder")]]},
        "Avisos de hoy": {"main": [[conexion("Formatear avisos")]]},
        "Formatear avisos": {"main": [[conexion("Responder avisos")]]},
        **conexiones_agente,
    }
    return flujo("Copiloto · agente de Telegram", nodos, conexiones)


def agente_chat_prueba() -> dict[str, Any]:
    """El mismo agente, para conversar desde el editor de n8n (botón «Open chat») sin Telegram."""
    chat = "Chat de prueba"
    nodos_agente, conexiones_agente = _agente(f"{{{{ $('{chat}').first().json.chatInput }}}}",
                                              f"={{{{ $('{chat}').first().json.sessionId }}}}")
    nodos = [
        nodo(chat, "@n8n/n8n-nodes-langchain.chatTrigger", 1.1, (0, 0), {"public": False, "options": {}}),
        nodo(CONFIG, "n8n-nodes-base.set", 3.4, (220, 0), asignaciones([("api_url", API_URL_EJEMPLO, "string")])),
        *nodos_agente,
    ]
    conexiones = {
        chat: {"main": [[conexion(CONFIG)]]},
        CONFIG: {"main": [[conexion("Agente copiloto")]]},
        **conexiones_agente,
    }
    return flujo("Copiloto · chat de prueba", nodos, conexiones)


# --- Flujo 4: avisos por Telegram (sin modelo) ------------------------------------------

MENSAJES_JS = f"""// Un mensaje por chat con sus avisos nuevos: «campo» (MDS y riego) y «sistema» (ingesta de datos;
// si chat_ids_sistema está vacío, van a los de campo). Sin chats configurados no se manda ni se confirma nada.
const cfg = $('{CONFIG}').first().json;
const lista = (ids) => String(ids || '').split(',').map((s) => s.trim()).filter(Boolean);
const campo = lista(cfg.chat_ids_campo);
const sistema = lista(cfg.chat_ids_sistema).length ? lista(cfg.chat_ids_sistema) : campo;
const r = $input.first().json;
const porChat = new Map();
for (const a of r.avisos || []) {{
  for (const chat_id of (a.destino === 'sistema' ? sistema : campo)) {{
    if (!porChat.has(chat_id)) porChat.set(chat_id, []);
    porChat.get(chat_id).push(a);
  }}
}}
const cabecera = 'Aviso del copiloto de riego' + (r.modulo && r.modulo.nombre ? ` · ${{r.modulo.nombre}}` : '');
return [...porChat].map(([chat_id, avisos]) => ({{ json: {{
  chat_id,
  claves: avisos.map((a) => a.clave),
  texto: [cabecera, ...avisos.map((a) => `${{a.icono}} ${{a.titulo}}\\n${{a.detalle}}`)].join('\\n\\n').slice(0, {LIMITE_TELEGRAM}),
}} }}));"""

CLAVES_ENVIADAS = "={{ JSON.stringify({ claves: [...new Set($('Mensajes').all().flatMap((i) => i.json.claves))] }) }}"


def avisos() -> dict[str, Any]:
    """Cada hora (06:50 a 21:50) pide los avisos pendientes, los manda y confirma los enviados.

    No usa el modelo: el texto lo arma el backend. Si Telegram falla no se confirma y el aviso sale
    en la siguiente consulta."""
    nodos = [
        nodo("Cada hora", "n8n-nodes-base.scheduleTrigger", 1.2, (0, 0),
             {"rule": {"interval": [{"field": "cronExpression", "expression": "50 6-21 * * *"}]}}),
        nodo(CONFIG, "n8n-nodes-base.set", 3.4, (220, 0), asignaciones([
            ("api_url", API_URL_EJEMPLO, "string"),
            ("chat_ids_campo", "ID_CHAT_ENCARGADO,ID_CHAT_SUBGERENTE", "string"),
            ("chat_ids_sistema", "ID_CHAT_ADMIN", "string"),
        ])),
        nodo("Avisos pendientes", "n8n-nodes-base.httpRequest", 4.2, (440, 0), {
            "url": url("/copiloto/avisos"), "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth", "sendQuery": True,
            "queryParameters": {"parameters": [{"name": "pendientes", "value": "true"}]},
            "options": {"timeout": 60000},
        }, CRED_TOKEN),
        nodo("Mensajes", "n8n-nodes-base.code", 2, (660, 0), {"jsCode": MENSAJES_JS}),
        telegram("Enviar aviso", (880, 0), "={{ $json.chat_id }}", "={{ $json.texto }}"),
        {**nodo("Confirmar enviados", "n8n-nodes-base.httpRequest", 4.2, (1100, 0), {
            "method": "POST", "url": url("/copiloto/avisos/confirmar"), "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth", "sendBody": True, "specifyBody": "json",
            "jsonBody": CLAVES_ENVIADAS, "options": {},
        }, CRED_TOKEN), "executeOnce": True},
    ]
    conexiones = {
        "Cada hora": {"main": [[conexion(CONFIG)]]},
        CONFIG: {"main": [[conexion("Avisos pendientes")]]},
        "Avisos pendientes": {"main": [[conexion("Mensajes")]]},
        "Mensajes": {"main": [[conexion("Enviar aviso")]]},
        "Enviar aviso": {"main": [[conexion("Confirmar enviados")]]},
    }
    return flujo("Copiloto · avisos por Telegram", nodos, conexiones)


def main() -> None:
    global _proveedor
    destino = AQUI / "flujos" / "avisos.json"  # sin modelo: el mismo para Anthropic y Devlum
    destino.write_text(json.dumps(avisos(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Escrito {destino} (6 nodos)")
    for proveedor in PROVEEDORES:
        _proveedor = proveedor
        destino = AQUI / "flujos" / ("" if proveedor == "anthropic" else proveedor)
        destino.mkdir(parents=True, exist_ok=True)
        for archivo, datos in (("informe_diario.json", informe_diario()), ("agente_telegram.json", agente_telegram()),
                               ("agente_chat_prueba.json", agente_chat_prueba())):
            if proveedor != "anthropic":
                datos["name"] += f" ({proveedor})"
            (destino / archivo).write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Escrito {destino / archivo} ({len(datos['nodes'])} nodos)")


if __name__ == "__main__":
    main()
