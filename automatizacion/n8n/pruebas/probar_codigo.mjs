// Ejecuta los nodos Code de los flujos con entradas simuladas, como lo haría n8n (sin n8n ni Docker).
// Uso: node automatizacion/n8n/pruebas/probar_codigo.mjs
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const dir = process.env.FLUJOS_DIR || fileURLToPath(new URL("../flujos", import.meta.url));
const cargar = (f) => JSON.parse(readFileSync(`${dir}/${f}`, "utf8"));
const codigo = (flujo, nombre) => flujo.nodes.find((n) => n.name === nombre).parameters.jsCode;

function correr(js, { entrada, nodos }) {
  const $input = { first: () => ({ json: entrada }), all: () => [{ json: entrada }] };
  const $ = (nombre) => ({ first: () => ({ json: nodos[nombre] }) });
  return new Function("$input", "$", js)($input, $);
}

const informe = cargar("informe_diario.json");
const agente = cargar("agente_telegram.json");
let ok = 0;

// --- Destinatarios
const dest = correr(codigo(informe, "Destinatarios"), {
  entrada: { text: "Buenos días" }, nodos: { "Configuración": { chat_ids: " 111, 222 ,," } },
});
assert.deepEqual(dest.map((d) => d.json), [{ chat_id: "111", texto: "Buenos días" }, { chat_id: "222", texto: "Buenos días" }]); ok++;
const destinatarios = (entrada) => correr(codigo(informe, "Destinatarios"), {
  entrada, nodos: { "Configuración": { chat_ids: "111" } },
})[0].json.texto;
assert.equal(destinatarios({ text: "x".repeat(6000) }).length, 4000); ok++; // límite de Telegram: 4096
assert.match(destinatarios({ error: "modelo caído" }), /^No pude redactar el informe/); ok++;
assert.equal(informe.nodes.find((n) => n.name === "Redactar informe").onError, "continueRegularOutput"); ok++;

// --- Disparadores con webhookId fijo (sin él, n8n no registra el webhook de Telegram al publicar)
const chatPrueba = cargar("agente_chat_prueba.json");
for (const [flujo, nombre] of [[agente, "Mensaje de Telegram"], [chatPrueba, "Chat de prueba"]]) {
  assert.match(flujo.nodes.find((n) => n.name === nombre).webhookId ?? "", /^[0-9a-f-]{36}$/); ok++;
}

// --- Respuesta del agente (expresión del nodo «Responder»)
const nodoAgente = agente.nodes.find((n) => n.name === "Agente copiloto");
assert.equal(nodoAgente.onError, "continueRegularOutput"); ok++;
const exprResponder = agente.nodes.find((n) => n.name === "Responder").parameters.text.replace(/^=\{\{|\}\}$/g, "");
const responder = ($json) => new Function("$json", `return ${exprResponder};`)($json);
assert.equal(responder({ output: "Plan de hoy: TE01 120 m³" }), "Plan de hoy: TE01 120 m³"); ok++;
assert.match(responder({ error: "timeout" }), /^No pude consultar los datos/); ok++;
assert.equal(responder({ output: "y".repeat(9000) }).length, 4000); ok++;

// --- Sugerencias desde alertas
const resumen = {
  fecha: "2026-11-08", modulo: { id: 1 },
  alertas: [
    { codigo: "estres_mds", severidad: "alta", titulo: "Estrés crítico", detalle: "MDS 253 µm", fecha: "2026-11-07", turno_codigo: null },
    { codigo: "plan_hoy_sin_publicar", severidad: "alta", titulo: "Borrador", detalle: "x", fecha: "2026-11-08", turno_codigo: null },
    { codigo: "desvio_plan_real", severidad: "media", titulo: "TE02", detalle: "x", fecha: "2026-11-07", turno_codigo: "TE02" },
    { codigo: "riego_sin_respuesta", severidad: "alta", titulo: "Sin respuesta", detalle: "y", fecha: null, turno_codigo: null },
  ],
};
const sug = correr(codigo(informe, "Sugerencias desde alertas"), { entrada: resumen, nodos: {} }).map((s) => s.json);
assert.equal(sug.length, 2);
assert.deepEqual(sug.map((s) => [s.tipo, s.alerta_codigo, s.fecha]), [["ajustar_riego", "estres_mds", "2026-11-07"], ["revisar_equipo", "riego_sin_respuesta", "2026-11-08"]]);
ok++;
assert.deepEqual(correr(codigo(informe, "Sugerencias desde alertas"), { entrada: { fecha: "x", modulo: { id: 1 }, alertas: [] }, nodos: {} }), []); ok++;

// --- Preparar (bot de Telegram)
const preparar = (texto, chat = 111) => correr(codigo(agente, "Preparar"), {
  entrada: {},
  nodos: {
    "Mensaje de Telegram": { message: { chat: { id: chat }, ...(texto === null ? {} : { text: texto }) } },
    "Configuración": { chat_ids_autorizados: "111, 222" },
  },
})[0].json;
assert.equal(preparar("hola", 999).tipo, "no_autorizado");
assert.equal(preparar("hola", 999).chat_id, "999");
assert.equal(preparar(null).tipo, "sin_texto");
assert.equal(preparar("/start").tipo, "ayuda");
assert.equal(preparar("/AYUDA").tipo, "ayuda");
assert.equal(preparar("/hoy").pregunta.startsWith("Dame el plan de riego de hoy"), true);
assert.equal(preparar("/hoy@CopilotoBot").pregunta.startsWith("Dame el plan de riego de hoy"), true);
assert.match(preparar("/turno TE03").pregunta, /turno TE03/);
assert.equal(preparar("¿Por qué subió el TE02?").pregunta, "¿Por qué subió el TE02?");
assert.equal(preparar("¿Por qué subió el TE02?").tipo, "agente");
assert.equal(preparar("x".repeat(5000)).pregunta.length, 1000);
assert.equal(preparar("/avisos").tipo, "avisos");
assert.equal(preparar("/avisos@GR_riegoBOT").tipo, "avisos");
assert.equal(preparar("/avisos", 999).tipo, "no_autorizado");
assert.deepEqual([preparar("/plan").tipo, preparar("/plan").dia], ["plan", "hoy"]);
assert.equal(preparar("/plan 23/11").dia, "23/11");
assert.equal(preparar("/plan pasado mañana").dia, "pasado mañana");
assert.equal(preparar("/plan@GR_riegoBOT mañana").dia, "mañana");
assert.equal(preparar("/plan " + "9".repeat(50)).dia.length, 20);
assert.equal(preparar("/hoy").dia, null);
ok += 20;

// --- /plan del bot (expresión del nodo «Responder plan»)
const exprPlan = agente.nodes.find((n) => n.name === "Responder plan").parameters.text.replace(/^=\{\{|\}\}$/g, "");
const responderPlan = ($json) => new Function("$json", `return ${exprPlan};`)($json);
assert.equal(responderPlan({ texto: "📋 Plan de riego del lunes 09/11/2026" }), "📋 Plan de riego del lunes 09/11/2026");
assert.match(responderPlan({ error: "422 - No entendí la fecha" }), /^No entendí la fecha\. Prueba con \/plan hoy/);
assert.equal(responderPlan({ texto: "z".repeat(5000) }).length, 4000);
ok += 3;

// --- /avisos del bot (Formatear avisos): título y resumen de cada uno
const formatear = (entrada) => correr(codigo(agente, "Formatear avisos"), {
  entrada, nodos: { Preparar: { chat_id: "111" } },
})[0].json;
const avisoMds = { clave: "mds_nivel:1:2026-11-07:alto", icono: "🟠", titulo: "El MDS subió a estrés alto",
  detalle: "El 07/11/2026 el MDS fue de 241 µm.", resumen: "El 07/11/2026 el MDS fue de 241 µm.", destino: "campo",
  enviado: true };
const avisoIngesta = { clave: "ingesta_fallida:1:2026-11-08:weatherlink", icono: "🔴",
  titulo: "La ingesta de WeatherLink (clima) falló", detalle: "Error: HTTP 503.", resumen: "Error: HTTP 503.",
  destino: "sistema", enviado: false };
const avisoPlan = { clave: "cronograma:1:2026-11-09:e7", icono: "✅", titulo: "Plan de riego publicado · lunes 09/11",
  detalle: "Plan del lunes 09/11/2026\n…\n• TE01 …\n   1) 06:00–07:00 …", resumen: "lunes 09/11 · versión 2 · 3,812 m³",
  destino: "cronogramas", enviado: false };
const conAvisos = formatear({ avisos: [avisoMds, avisoIngesta, avisoPlan] });
assert.equal(conAvisos.chat_id, "111");
assert.match(conAvisos.texto, /^Avisos recientes:\n\n🟠 El MDS subió a estrés alto \(ya avisado\)\nEl 07\/11\/2026/);
assert.match(conAvisos.texto, /✅ Plan de riego publicado · lunes 09\/11\nlunes 09\/11 · versión 2 · 3,812 m³\n\nPara ver un plan completo: \/plan DD\/MM$/);
assert.ok(!conAvisos.texto.includes("1) 06:00"));  // el listado usa el resumen, no el plan completo
assert.match(formatear({ avisos: [] }).texto, /^No hay avisos por ahora/);
assert.match(formatear({ error: "timeout" }).texto, /^No pude consultar los avisos/);
ok += 5;

// --- Flujo de avisos (un mensaje por aviso y por chat)
// Sin modelo: un solo archivo para Anthropic y Devlum.
const flujoAvisos = JSON.parse(readFileSync(new URL("../flujos/avisos.json", import.meta.url), "utf8"));
const mensajes = (cfg, avisos) => correr(codigo(flujoAvisos, "Mensajes"), {
  entrada: { modulo: { nombre: "ENSUEÑO 1 MODULO 5" }, avisos }, nodos: { "Configuración": cfg },
}).map((m) => m.json);
const separados = mensajes({ chat_ids_campo: "111, 222", chat_ids_sistema: "333", chat_ids_cronogramas: "444" },
  [avisoMds, avisoIngesta, avisoPlan]);
assert.deepEqual(separados.map((m) => [m.chat_id, m.claves]), [
  ["111", [avisoMds.clave]], ["222", [avisoMds.clave]], ["333", [avisoIngesta.clave]], ["444", [avisoPlan.clave]]]);
assert.equal(separados[0].texto, "🟠 El MDS subió a estrés alto\n\nEl 07/11/2026 el MDS fue de 241 µm.");
assert.ok(separados[3].texto.includes("   1) 06:00–07:00"));  // el mensaje push lleva el plan completo
const respaldo = mensajes({ chat_ids_campo: "111", chat_ids_sistema: "", chat_ids_cronogramas: "" },
  [avisoMds, avisoIngesta, avisoPlan]);
assert.deepEqual(respaldo.map((m) => [m.chat_id, m.claves[0]]),
  [["111", avisoMds.clave], ["111", avisoIngesta.clave], ["111", avisoPlan.clave]]);  // sin chats propios: a campo
assert.deepEqual(mensajes({ chat_ids_campo: "", chat_ids_sistema: "", chat_ids_cronogramas: "" }, [avisoMds]), []);
assert.deepEqual(mensajes({ chat_ids_campo: "111" }, []), []);
const largo = mensajes({ chat_ids_campo: "111" }, [{ ...avisoMds, detalle: "x".repeat(6000) }]);
assert.equal(largo[0].texto.length, 4000);
assert.equal(flujoAvisos.nodes.find((n) => n.name === "Confirmar enviados").executeOnce, true);
ok += 8;

console.log(`OK: ${ok} comprobaciones de los nodos Code`);
