"""Prueba los flujos en un n8n real (Docker) contra la API, sin claves de Claude ni de Telegram.

Qué hace:
1. Importa en el contenedor la credencial del token del agente y los dos flujos reales.
2. Importa variantes de prueba: el informe sin Claude/Telegram (trigger manual -> resumen ->
   sugerencias) y el bot sin Claude/Telegram con cinco mensajes simulados.
3. Las ejecuta con ``n8n execute`` y comprueba: estado de cada ejecución, sugerencias creadas o
   marcadas como duplicadas, y a qué salida va cada mensaje del bot.

Requisitos: la API corriendo (p. ej. uvicorn en :8000 contra riego_dev), un token creado con
``python -m app.cli crear-token-agente n8n-local --archivo <ruta>`` y un contenedor de n8n:

    docker run -d --name n8n-copiloto-prueba -p 127.0.0.1:5679:5678 \
      -e N8N_ENCRYPTION_KEY=<aleatoria> -e WEBHOOK_URL=http://localhost:5679/ -e GENERIC_TIMEZONE=America/Lima docker.n8n.io/n8nio/n8n:<versión>

Uso:
    python automatizacion/n8n/pruebas/probar_n8n_local.py --token-archivo <ruta> \
        [--api-url http://host.docker.internal:8000] [--contenedor n8n-copiloto-prueba]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FLUJOS = Path(__file__).resolve().parents[1] / "flujos"
CRED_ID = "credTokenAgente01"
SALIDAS_BOT = ("agente", "ayuda", "sin_texto", "no_autorizado")
MENSAJES = {  # caso -> (mensaje de Telegram, salida esperada)
    "autorizado": ({"chat": {"id": 111}, "text": "¿Por qué subió el TE02?"}, "agente"),
    "comando": ({"chat": {"id": 222}, "text": "/hoy"}, "agente"),
    "ayuda": ({"chat": {"id": 111}, "text": "/start"}, "ayuda"),
    "sin_texto": ({"chat": {"id": 111}}, "sin_texto"),
    "no_autorizado": ({"chat": {"id": 999}, "text": "hola"}, "no_autorizado"),
}


def nodo(nombre: str, tipo: str, version: float, parametros: dict | None = None) -> dict:
    return {"parameters": parametros or {}, "id": nombre.replace(" ", "-"), "name": nombre, "type": tipo,
            "typeVersion": version, "position": [0, 0]}


def enlace(destino: str) -> dict:
    return {"node": destino, "type": "main", "index": 0}


def con_credencial(flujo: dict, wid: str, api_url: str) -> dict:
    flujo = copy.deepcopy(flujo)
    flujo["id"] = wid
    for n in flujo["nodes"]:
        if "httpHeaderAuth" in n.get("credentials", {}):
            n["credentials"]["httpHeaderAuth"]["id"] = CRED_ID
        if n["name"] == "Configuración":
            for a in n["parameters"]["assignments"]["assignments"]:
                a["value"] = api_url if a["name"] == "api_url" else ("111,222" if a["name"].startswith("chat_ids")
                                                                     else a["value"])
    return flujo


def preparar(api_url: str) -> dict[str, dict]:
    informe = json.loads((FLUJOS / "informe_diario.json").read_text(encoding="utf-8"))
    agente = json.loads((FLUJOS / "agente_telegram.json").read_text(encoding="utf-8"))
    flujos = {"wfInformeReal001": con_credencial(informe, "wfInformeReal001", api_url),
              "wfAgenteReal0001": con_credencial(agente, "wfAgenteReal0001", api_url)}

    prueba = con_credencial(informe, "wfInformePrueba1", api_url)
    fuera = {"Cada día 06:15", "Redactar informe", "Claude", "Destinatarios", "Enviar por Telegram"}
    prueba["name"] = "PRUEBA informe sin LLM"
    prueba["nodes"] = [n for n in prueba["nodes"] if n["name"] not in fuera] + [
        nodo("Inicio manual", "n8n-nodes-base.manualTrigger", 1)]
    prueba["connections"] = {
        "Inicio manual": {"main": [[enlace("Configuración")]]},
        "Configuración": {"main": [[enlace("Resumen del copiloto")]]},
        "Resumen del copiloto": {"main": [[enlace("Sugerencias desde alertas")]]},
        "Sugerencias desde alertas": {"main": [[enlace("Crear sugerencia")]]},
    }
    flujos[prueba["id"]] = prueba

    quitar = {"Mensaje de Telegram", "Agente copiloto", "Claude", "Memoria del chat", "Responder", "Ayuda",
              "Solo texto", "No autorizado"}
    for i, (caso, (mensaje, _)) in enumerate(MENSAJES.items()):
        f = con_credencial(agente, f"wfBotPrueba{i:05d}", api_url)
        f["name"] = f"PRUEBA bot {caso}"
        herramientas = {n["name"] for n in f["nodes"] if n["type"] == "n8n-nodes-base.httpRequestTool"}
        f["nodes"] = [n for n in f["nodes"] if n["name"] not in quitar | herramientas] + [
            nodo("Inicio manual", "n8n-nodes-base.manualTrigger", 1),
            nodo("Mensaje de Telegram", "n8n-nodes-base.code", 2,
                 {"jsCode": f"return [{{ json: {{ message: {json.dumps(mensaje, ensure_ascii=False)} }} }}];"}),
            *[nodo(f"SALIDA {s}", "n8n-nodes-base.noOp", 1) for s in SALIDAS_BOT],
        ]
        f["connections"] = {
            "Inicio manual": {"main": [[enlace("Mensaje de Telegram")]]},
            "Mensaje de Telegram": {"main": [[enlace("Configuración")]]},
            "Configuración": {"main": [[enlace("Preparar")]]},
            "Preparar": {"main": [[enlace("¿Qué hacer?")]]},
            "¿Qué hacer?": {"main": [[enlace(f"SALIDA {s}")] for s in SALIDAS_BOT]},
        }
        flujos[f["id"]] = f
    return flujos


def docker(contenedor: str, *args: str, broker: bool = False) -> str:
    entorno = ["-e", "N8N_RUNNERS_BROKER_PORT=5690", "-e", "N8N_PORT=5691"] if broker else []
    resultado = subprocess.run(["docker", "exec", *entorno, contenedor, *args], capture_output=True, text=True,
                               encoding="utf-8", env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    return resultado.stdout + resultado.stderr


def ejecutar(contenedor: str, wid: str) -> dict:
    texto = docker(contenedor, "n8n", "execute", f"--id={wid}", "--rawOutput", broker=True)
    try:
        return json.loads(texto[texto.index("{"):])
    except ValueError:
        raise SystemExit(f"No se pudo leer la ejecución de {wid}:\n{texto[-2000:]}") from None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--token-archivo", type=Path, required=True)
    p.add_argument("--api-url", default="http://host.docker.internal:8000")
    p.add_argument("--contenedor", default="n8n-copiloto-prueba")
    args = p.parse_args()
    token = args.token_archivo.read_text(encoding="utf-8").strip()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "credenciales.json").write_text(json.dumps([{
            "id": CRED_ID, "name": "Token agente copiloto", "type": "httpHeaderAuth",
            "data": {"name": "X-Token-Agente", "value": token}}]), encoding="utf-8")
        flujos = preparar(args.api_url)
        for wid, f in flujos.items():
            (tmp / f"{wid}.json").write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["docker", "cp", str(tmp), f"{args.contenedor}:/tmp/copiloto"], check=True,
                       env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    print(docker(args.contenedor, "n8n", "import:credentials", "--input=/tmp/copiloto/credenciales.json").strip()
          .splitlines()[-1])
    for wid in flujos:
        salida = docker(args.contenedor, "n8n", "import:workflow", f"--input=/tmp/copiloto/{wid}.json").strip()
        assert "Successfully imported" in salida, (wid, salida[-500:])
    print(f"Importados {len(flujos)} flujos (2 reales y {len(flujos) - 2} de prueba).")

    fallos = 0
    for corrida in (1, 2):
        d = ejecutar(args.contenedor, "wfInformePrueba1")
        run = d["data"]["resultData"]["runData"]
        creadas = run.get("Crear sugerencia", [{}])[0].get("data", {}).get("main", [[]])[0]
        dup = sum(1 for c in creadas if c["json"].get("duplicada"))
        ok = d["status"] == "success" and (corrida == 1 or dup == len(creadas))
        fallos += not ok
        print(f"{'OK ' if ok else 'MAL'} informe corrida {corrida}: {d['status']}, {len(creadas)} sugerencias "
              f"({len(creadas) - dup} nuevas, {dup} ya existían)")

    for i, (caso, (_, esperada)) in enumerate(MENSAJES.items()):
        d = ejecutar(args.contenedor, f"wfBotPrueba{i:05d}")
        salidas = [k.removeprefix("SALIDA ") for k in d["data"]["resultData"]["runData"] if k.startswith("SALIDA")]
        ok = d["status"] == "success" and salidas == [esperada]
        fallos += not ok
        print(f"{'OK ' if ok else 'MAL'} bot «{caso}»: salida {salidas} (esperada {esperada})")

    print("Todo bien." if not fallos else f"{fallos} prueba(s) fallaron.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
