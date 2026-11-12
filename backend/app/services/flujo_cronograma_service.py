"""Flujo F4: versiones inmutables, transiciones, lecturas y cola transaccional de correo.

Todas las mutaciones toman primero el cronograma FOR UPDATE. Solo se hace flush;
DbSesion confirma cronograma, riego, eventos, auditoría y correos conjuntamente.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import Conflicto, DatosInvalidos, NoEncontrado, SinPermiso
from app.core.tiempo import ahora_utc, hoy_lima
from app.models import Cronograma, CronogramaEvento, CronogramaVersion, Modulo, Usuario
from app.models.enums import EstadoCronograma, EstadoRiego, OrigenRiego, OrigenVersion, RolUsuario, TipoEventoCronograma
from app.repositories import cronogramas as repo
from app.repositories import riego as repo_riego
from app.schemas.cronograma import EdicionEntrada, GuardarVersionEntrada
from app.services import auditoria_service, correo_service, cronograma_service, riego_service
from app.services.contexto import ContextoPeticion

EDITORES = (RolUsuario.admin, RolUsuario.encargado)
LECTORES = (*EDITORES, RolUsuario.subgerente)
PUBLICADOS = cronograma_service.ESTADOS_PUBLICADOS
CAMPOS_CICLO = (
    "ciclo", "riego_m3ha", "riego_m3", "duracion_min", "inicio_min", "fin_min", "hora_inicio",
    "hora_fin", "fin_dia_siguiente", "m3ha_p10", "m3ha_p90", "duracion_p10", "duracion_p90",
    "inicio_desde_min", "inicio_hasta_min", "ciclo_modelo", "duracion_manual", "campos_editados",
)
CAMPOS_TURNO = ("turno_id", "n_ciclos", "n_ciclos_modelo", "factor_min_por_m3ha", "area_ha", "caudal_m3h")


def obtener(db: Session, cronograma_id: int, actor: Usuario, roles: tuple[RolUsuario, ...], *,
            bloquear: bool = False) -> Cronograma:
    if actor.rol not in roles:
        raise SinPermiso()
    crono = repo.obtener(db, cronograma_id, bloquear=bloquear)
    if crono is None:
        raise NoEncontrado("Cronograma no encontrado")
    cronograma_service._visible(crono, actor)
    return crono


def _estado(crono: Cronograma, permitidos: tuple[EstadoCronograma, ...]) -> None:
    if crono.estado not in permitidos:
        raise Conflicto("El estado actual del cronograma no permite esta acción")


def _lock(crono: Cronograma, lock_version: int) -> None:
    if lock_version != crono.lock_version:
        raise Conflicto("Otro usuario modificó el cronograma; recarga")


def _evento(db: Session, crono: Cronograma, version_id: int | None, actor: Usuario,
            tipo: TipoEventoCronograma, *, detalle: dict | None = None,
            comentario: str | None = None, motivo_codigo: str | None = None) -> None:
    db.add(CronogramaEvento(
        cronograma_id=crono.id, version_id=version_id, usuario_id=actor.id, tipo=tipo,
        ocurrido_at=ahora_utc(), detalle=detalle, comentario=comentario, motivo_codigo=motivo_codigo,
    ))


def _auditar(db: Session, crono: Cronograma, actor: Usuario, accion: str,
             contexto: ContextoPeticion | None, detalle: dict | None = None) -> None:
    auditoria_service.registrar(db, accion=accion, entidad="cronograma", entidad_id=crono.id,
                                actor=actor, contexto=contexto, detalle=detalle)


def _terminar(db: Session, crono: Cronograma, actor: Usuario) -> dict[str, Any]:
    crono.lock_version += 1
    db.flush()
    db.refresh(crono)  # updated_at lo mantiene el trigger
    return cronograma_service._detalle(db, crono, actor)


def _base(db: Session, crono: Cronograma, basada_en_id: int) -> CronogramaVersion:
    """Versión sobre la que se edita: el borrador abierto o, en un publicado sin borrador de
    cambios, la versión publicada (guardar abre el borrador de cambios, §3.2 «editar o regenerar»)."""
    _estado(crono, (EstadoCronograma.borrador, *PUBLICADOS))
    esperada = crono.borrador_version_id
    if esperada is None and crono.estado in PUBLICADOS:
        esperada = crono.version_publicada_id
    if esperada is None:
        raise Conflicto("No hay una versión que editar")
    if basada_en_id != esperada:
        raise Conflicto("La versión base cambió; recarga el cronograma")
    base = repo.version(db, basada_en_id)
    if base is None or base.cronograma_id != crono.id:
        raise DatosInvalidos("La versión base no pertenece al cronograma")
    return base


def _calcular(db: Session, crono: Cronograma, base: CronogramaVersion,
              datos: EdicionEntrada) -> tuple[list[dict], list[dict], list[dict], int]:
    turnos = {t.turno_id: {k: getattr(t, k) for k in CAMPOS_TURNO} for t in base.turnos}
    ciclos = {t: [] for t in turnos}
    for c in base.ciclos:
        fila = {k: getattr(c, k) for k in CAMPOS_CICLO}
        fila["campos_editados"] = []
        ciclos[c.turno_id].append(fila)
    recibidos = set()
    cambios = 0
    for t in datos.turnos:
        if t.turno_id in recibidos:
            raise DatosInvalidos("No se puede repetir un turno en la edición")
        recibidos.add(t.turno_id)
        if t.turno_id not in turnos:
            raise DatosInvalidos("El turno no pertenece a la versión base")
        if not 1 <= t.n_ciclos <= 5 or len(t.ciclos) != t.n_ciclos:
            raise DatosInvalidos("El número de ciclos debe estar entre 1 y 5 y coincidir con la lista de ciclos")
        if sorted(c.ciclo for c in t.ciclos) != list(range(1, t.n_ciclos + 1)):
            raise DatosInvalidos("Los ciclos deben numerarse de 1 a n_ciclos sin repetir")
        turno = turnos[t.turno_id]
        anteriores = {c["ciclo"]: c for c in ciclos[t.turno_id]}
        cambia_n = turno["n_ciclos"] != t.n_ciclos
        cambios += int(cambia_n) + len(set(anteriores) - {c.ciclo for c in t.ciclos})
        turno["n_ciclos"] = t.n_ciclos
        nuevos = []
        for c in t.ciclos:
            riego_service.validar_ciclo(c.inicio_min, c.duracion_min, c.riego_m3ha)
            anterior = anteriores.get(c.ciclo)
            # §3.4: los ciclos no editados conservan exactamente los valores del modelo.
            igual = anterior is not None and all(getattr(c, k) == anterior[k] for k in (
                "riego_m3ha", "inicio_min", "duracion_min", "duracion_manual",
            ))
            if igual:
                nuevo = dict(anterior)
            else:
                m3ha = round(c.riego_m3ha, 2)
                duracion = c.duracion_min
                if not c.duracion_manual:
                    factor = turno["factor_min_por_m3ha"]
                    if factor is None or not math.isfinite(factor) or factor <= 0:
                        raise DatosInvalidos("El turno no tiene un factor de duración válido; indica una duración manual")
                    duracion = m3ha * factor
                inicio, duracion = round(c.inicio_min, 1), round(duracion, 1)
                riego_service.validar_ciclo(inicio, duracion, m3ha)
                fin = round(inicio + duracion, 1)
                nuevo = {k: anterior[k] if anterior else None for k in CAMPOS_CICLO}
                nuevo.update(
                    ciclo=c.ciclo, riego_m3ha=m3ha, riego_m3=round(m3ha * turno["area_ha"], 1),
                    inicio_min=inicio, duracion_min=duracion, fin_min=fin,
                    hora_inicio=riego_service.hora_minuto(inicio), hora_fin=riego_service.hora_minuto(fin),
                    fin_dia_siguiente=fin >= 1440, duracion_manual=c.duracion_manual,
                )
            nuevo["ciclo_modelo"] = anterior["ciclo_modelo"] if anterior else None
            campos = [k for k in ("riego_m3ha", "inicio_min", "duracion_min")
                      if anterior is None or nuevo[k] != anterior[k]]
            cambios += len(campos) + int(anterior is not None and nuevo["duracion_manual"] != anterior["duracion_manual"])
            nuevo["campos_editados"] = campos + (["n_ciclos"] if cambia_n else [])
            nuevos.append(nuevo)
        ciclos[t.turno_id] = nuevos
    avisos = []
    filas = []
    codigos = {t.id: t.codigo for t in repo_riego.turnos_de_modulo(db, crono.modulo_id)}
    for turno_id, turno in turnos.items():
        lista = sorted(ciclos[turno_id], key=lambda c: c["inicio_min"])
        for previo, actual in zip(lista, lista[1:]):
            if actual["inicio_min"] < previo["fin_min"]:
                avisos.append({"turno_id": turno_id, "ciclo": actual["ciclo"], "tipo": "solape",
                               "mensaje": f"{codigos[turno_id]}: el ciclo {actual['ciclo']} se solapa con el anterior"})
        filas.extend({"turno_id": turno_id, **c} for c in sorted(lista, key=lambda c: c["ciclo"]))
    return list(turnos.values()), filas, avisos, cambios


def recalcular(db: Session, cronograma_id: int, datos: EdicionEntrada, actor: Usuario) -> dict:
    crono = obtener(db, cronograma_id, actor, EDITORES)
    base = _base(db, crono, datos.basada_en_id)
    turnos, ciclos, avisos, _ = _calcular(db, crono, base, datos)
    salida = cronograma_service._version_salida(db, base, crono, db.get(Modulo, crono.modulo_id))
    salida.pop("id")
    salida.pop("numero")
    anteriores = {t["turno_id"]: t for t in salida["turnos"]}
    for t in turnos:
        lista = [c for c in ciclos if c["turno_id"] == t["turno_id"]]
        anteriores[t["turno_id"]].update(t, ciclos=lista,
            total_m3ha=round(sum(c["riego_m3ha"] for c in lista), 2),
            total_m3=round(sum(c["riego_m3"] for c in lista), 1),
            total_min=round(sum(c["duracion_min"] for c in lista), 1))
    salida.update(origen=_origen(crono).value, creado_at=ahora_utc(), creado_por=actor.username,
                  publicada_at=None, publicada_por=None, es_borrador=True, es_publicada=False,
                  modelo_version=None, generacion_id=None, regenerado=False,
                  motivo_codigo=None, motivo_comentario=None, avisos=avisos,
                  total_m3=round(sum(t["total_m3"] for t in salida["turnos"]), 1))
    return salida


def _origen(crono: Cronograma) -> OrigenVersion:
    return OrigenVersion.correccion if crono.estado == EstadoCronograma.borrador else OrigenVersion.edicion


def guardar_version(db: Session, cronograma_id: int, datos: GuardarVersionEntrada, actor: Usuario,
                    contexto: ContextoPeticion | None = None) -> dict:
    crono = obtener(db, cronograma_id, actor, EDITORES, bloquear=True)
    _lock(crono, datos.lock_version)
    base = _base(db, crono, datos.basada_en_id)
    turnos, ciclos, _, cambios = _calcular(db, crono, base, datos)
    if not cambios:
        raise DatosInvalidos("No hay cambios")
    if not datos.motivo_codigo or not repo.motivo_activo(db, datos.motivo_codigo):
        raise DatosInvalidos("Indica un motivo de corrección activo")
    version = CronogramaVersion(
        cronograma_id=crono.id, numero=repo.max_numero(db, crono.id) + 1, origen=_origen(crono),
        basada_en_id=base.id, modelo_version_id=None, generacion_id=None, creado_por=actor.id,
        preliminar=base.preliminar, datos_incompletos=base.datos_incompletos,
        motivo_codigo=datos.motivo_codigo, motivo_comentario=datos.motivo_comentario,
    )
    db.add(version)
    db.flush()
    repo.insertar_turnos(db, [{"version_id": version.id, **t} for t in turnos])
    repo.insertar_ciclos(db, [{"version_id": version.id, **c} for c in ciclos])
    crono.borrador_version_id = version.id
    detalle = {"version": version.numero, "motivo_codigo": datos.motivo_codigo, "cambios": cambios}
    _evento(db, crono, version.id, actor, TipoEventoCronograma.corregido, detalle=detalle,
            motivo_codigo=datos.motivo_codigo, comentario=datos.motivo_comentario)
    _auditar(db, crono, actor, "corregir", contexto, detalle)
    return _terminar(db, crono, actor)


def alternativas(db: Session, cronograma_id: int, actor: Usuario) -> dict:
    crono = obtener(db, cronograma_id, actor, EDITORES)
    version = repo.version(db, crono.borrador_version_id or crono.version_publicada_id)
    visitadas = set()
    while version is not None and version.id not in visitadas:
        visitadas.add(version.id)
        if version.generacion_id is not None:
            return repo.alternativas(db, version.generacion_id, crono.fecha)
        version = repo.version(db, version.basada_en_id)
    return {}


def descartar_borrador(db: Session, cronograma_id: int, actor: Usuario,
                       contexto: ContextoPeticion | None = None) -> dict:
    crono = obtener(db, cronograma_id, actor, EDITORES, bloquear=True)
    if crono.estado == EstadoCronograma.borrador:
        raise Conflicto("Un cronograma en borrador no tiene versión publicada a la que volver")
    _estado(crono, PUBLICADOS)
    if crono.borrador_version_id is None:
        raise Conflicto("No hay un borrador abierto para descartar")
    version_id = crono.borrador_version_id
    crono.borrador_version_id = None
    _evento(db, crono, version_id, actor, TipoEventoCronograma.borrador_descartado)
    _auditar(db, crono, actor, "descartar_borrador", contexto, {"version_id": version_id})
    return _terminar(db, crono, actor)


def _comparar(db: Session, base: CronogramaVersion, contra: CronogramaVersion, modulo_id: int) -> list[dict]:
    codigos = {t.id: t.codigo for t in repo_riego.turnos_de_modulo(db, modulo_id)}
    cambios = []

    def agregar(t, c, campo, antes, despues):
        if antes != despues:
            cambios.append({"turno_id": t, "turno_codigo": codigos[t], "ciclo": c,
                            "campo": campo, "antes": antes, "despues": despues})

    ts_a, ts_b = {t.turno_id: t.n_ciclos for t in base.turnos}, {t.turno_id: t.n_ciclos for t in contra.turnos}
    for t in sorted(ts_a.keys() | ts_b.keys()):
        agregar(t, None, "n_ciclos", ts_a.get(t), ts_b.get(t))
    cs_a = {(c.turno_id, c.ciclo): c for c in base.ciclos}
    cs_b = {(c.turno_id, c.ciclo): c for c in contra.ciclos}
    campos = ("riego_m3ha", "hora_inicio", "duracion_min")
    for t, n in sorted(cs_a.keys() | cs_b.keys()):
        a, b = cs_a.get((t, n)), cs_b.get((t, n))
        if a is None or b is None:
            agregar(t, n, "ciclo", {k: getattr(a, k) for k in campos} if a else None,
                    {k: getattr(b, k) for k in campos} if b else None)
        else:
            for k in campos:
                agregar(t, n, k, getattr(a, k), getattr(b, k))
    return cambios


def diferencias(db: Session, cronograma_id: int, base: int, contra: int, actor: Usuario) -> dict:
    crono = obtener(db, cronograma_id, actor, (*LECTORES, RolUsuario.programador))
    a, b = repo.version_por_numero(db, crono.id, base), repo.version_por_numero(db, crono.id, contra)
    if a is None or b is None:
        raise NoEncontrado("Versión no encontrada")
    if actor.rol == RolUsuario.programador:
        # Se limpia visto_version_id al publicar cambios: el evento conserva la versión
        # confirmada por este programador sin exponer borradores ni versiones ajenas.
        vista = repo.ultimo_evento(db, crono.id, TipoEventoCronograma.visto_programador, actor.id, a.id)
        if a.publicada_at is None or b.id != crono.version_publicada_id or vista is None:
            raise SinPermiso("Solo puedes comparar tu versión vista con la publicada actual")
    return {"base": base, "contra": contra, "cambios": _comparar(db, a, b, crono.modulo_id)}


def _resumen(cambios: list[dict]) -> list[str]:
    etiquetas = {"n_ciclos": "número de ciclos", "riego_m3ha": "m³/ha",
                 "hora_inicio": "inicio", "duracion_min": "min"}
    salida = []
    for c in cambios[:20]:
        prefijo = c["turno_codigo"] + (f" ciclo {c['ciclo']}" if c["ciclo"] is not None else "")
        if c["campo"] == "ciclo":
            salida.append(f"{prefijo}: {'agregado' if c['antes'] is None else 'quitado'}")
            continue
        def valor(v):
            if isinstance(v, float):
                texto = f"{v:.2f}".rstrip("0")
                return (texto + "0" if texto.endswith(".") else texto).replace(".", ",")
            return str(v)
        salida.append(f"{prefijo}: {valor(c['antes'])} → {valor(c['despues'])} {etiquetas[c['campo']]}")
    return salida


def _correo(db: Session, crono: Cronograma, version: CronogramaVersion, actor: Usuario,
             tipo: str, roles: tuple[RolUsuario, ...], **extras) -> None:
    titulos = {"cronograma_publicado": "Cronograma publicado", "cronograma_modificado": "Cronograma modificado",
               "cronograma_visto": "Visto del programador", "correccion_solicitada": "Corrección solicitada",
               "correccion_mantenida": "Versión mantenida"}
    dias = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
    fecha = f"{dias[crono.fecha.weekday()]} {crono.fecha:%d/%m}"
    modulo = db.get(Modulo, crono.modulo_id)
    contexto = {"modulo": modulo.codigo, "fecha": fecha, "version": version.numero,
                "usuario": actor.username, "resumen": [], "retrospectiva": False,
                "motivo": None, "comentario": None,
                "enlace": f"{settings.frontend_url.rstrip('/')}/cronogramas/{crono.id}", **extras}
    for rol in roles:
        correo_service.encolar(db, tipo=tipo, asunto=f"{titulos[tipo]} · {modulo.codigo} · {fecha}",
                               rol_destino=rol, cronograma_id=crono.id, contexto=contexto)


def _limpiar_solicitud(crono: Cronograma) -> None:
    crono.correccion_solicitada_at = None
    crono.correccion_solicitada_por = None
    crono.correccion_solicitada_motivo = None


def publicar(db: Session, cronograma_id: int, lock_version: int, actor: Usuario,
             contexto: ContextoPeticion | None = None) -> dict:
    crono = obtener(db, cronograma_id, actor, EDITORES, bloquear=True)
    _lock(crono, lock_version)
    _estado(crono, (EstadoCronograma.borrador, *PUBLICADOS))
    if crono.borrador_version_id is None:
        raise Conflicto("No hay un borrador abierto para publicar")
    version = repo.version(db, crono.borrador_version_id)
    anterior = repo.version(db, crono.version_publicada_id)
    cambios = anterior is not None
    retrospectiva = cambios and crono.fecha < hoy_lima()
    estaba_visto = crono.visto_version_id is not None
    solicitada = crono.estado == EstadoCronograma.correccion_solicitada
    resumen = _resumen(_comparar(db, anterior, version, crono.modulo_id)) if cambios else []
    version.publicada_at, version.publicada_por = ahora_utc(), actor.id
    crono.version_publicada_id, crono.borrador_version_id = version.id, None
    crono.num_publicaciones = crono.num_publicaciones + 1 if cambios else 1
    crono.estado = EstadoCronograma.visto if retrospectiva and estaba_visto else EstadoCronograma.publicado
    # Una corrección retrospectiva conserva el Visto histórico, sin atribuir uno nuevo.
    if not retrospectiva:
        crono.visto_version_id = crono.visto_programador_at = crono.visto_programador_por = None
    if solicitada:
        _limpiar_solicitud(crono)
        _evento(db, crono, version.id, actor, TipoEventoCronograma.correccion_atendida)
    tipo = TipoEventoCronograma.modificado if cambios else TipoEventoCronograma.publicado
    _evento(db, crono, version.id, actor, tipo, detalle={"version": version.numero, "retrospectiva": retrospectiva})
    _auditar(db, crono, actor, "publicar_cambios" if cambios else "publicar", contexto,
             {"version": version.numero, "retrospectiva": retrospectiva})
    avisos = riego_service.sincronizar_provisional(db, crono, version, actor, solo_existentes=True) if cambios else []
    roles = (RolUsuario.subgerente,) if retrospectiva else (RolUsuario.programador, RolUsuario.subgerente)
    _correo(db, crono, version, actor, "cronograma_modificado" if cambios else "cronograma_publicado",
            roles, resumen=resumen, retrospectiva=retrospectiva)
    return {**_terminar(db, crono, actor), "avisos": avisos}


def visto(db: Session, cronograma_id: int, version_id: int, actor: Usuario,
          contexto: ContextoPeticion | None = None) -> dict:
    crono = obtener(db, cronograma_id, actor, (RolUsuario.admin, RolUsuario.programador), bloquear=True)
    _estado(crono, (EstadoCronograma.publicado,))
    if version_id != crono.version_publicada_id:
        raise Conflicto("Hay una versión publicada más nueva; ábrela de nuevo")
    if crono.fecha < hoy_lima():
        raise DatosInvalidos("El Visto solo se confirma para hoy o días futuros")
    crono.estado, crono.visto_version_id = EstadoCronograma.visto, version_id
    crono.visto_programador_at, crono.visto_programador_por = ahora_utc(), actor.id
    version = repo.version(db, version_id)
    _evento(db, crono, version_id, actor, TipoEventoCronograma.visto_programador)
    _auditar(db, crono, actor, "visto_programador", contexto, {"version_id": version_id})
    avisos = riego_service.sincronizar_provisional(db, crono, version, actor)
    _correo(db, crono, version, actor, "cronograma_visto", (RolUsuario.subgerente,), resumen=avisos)
    return {**_terminar(db, crono, actor), "avisos": avisos}


def vista(db: Session, cronograma_id: int, actor: Usuario, contexto: ContextoPeticion | None = None) -> None:
    # Solo registra la apertura: sin FOR UPDATE para no frenar a quien esté editando.
    crono = obtener(db, cronograma_id, actor, (RolUsuario.programador, RolUsuario.subgerente))
    programador = actor.rol == RolUsuario.programador
    version_id = crono.version_publicada_id if programador else crono.borrador_version_id or crono.version_publicada_id
    tipo = TipoEventoCronograma.abierto_programador if programador else TipoEventoCronograma.visto_subgerente
    _auditar(db, crono, actor, "vista_programador" if programador else "vista_subgerente", contexto,
             {"version_id": version_id})
    ultimo = repo.ultimo_evento(db, crono.id, tipo, actor.id, version_id)
    if ultimo is None or ahora_utc() - ultimo >= dt.timedelta(minutes=30):
        _evento(db, crono, version_id, actor, tipo)
    # La apertura no modifica el cronograma y no invalida una edición en curso.
    db.flush()


def solicitar_correccion(db: Session, cronograma_id: int, version_id: int, motivo: str, actor: Usuario,
                         contexto: ContextoPeticion | None = None) -> dict:
    crono = obtener(db, cronograma_id, actor, (RolUsuario.admin, RolUsuario.subgerente), bloquear=True)
    _estado(crono, (EstadoCronograma.publicado, EstadoCronograma.visto))
    if version_id != crono.version_publicada_id:
        raise Conflicto("Hay una versión publicada más nueva; ábrela de nuevo")
    motivo = _texto(motivo, "El motivo")
    crono.estado = EstadoCronograma.correccion_solicitada
    crono.correccion_solicitada_at, crono.correccion_solicitada_por = ahora_utc(), actor.id
    crono.correccion_solicitada_motivo = motivo
    _evento(db, crono, version_id, actor, TipoEventoCronograma.correccion_solicitada, comentario=motivo)
    _auditar(db, crono, actor, "solicitar_correccion", contexto, {"version_id": version_id, "motivo": motivo})
    _correo(db, crono, repo.version(db, version_id), actor, "correccion_solicitada", (RolUsuario.encargado,), motivo=motivo)
    return _terminar(db, crono, actor)


def _texto(valor: str, nombre: str) -> str:
    valor = valor.strip()
    if not 5 <= len(valor) <= 1000:
        raise DatosInvalidos(f"{nombre} debe tener entre 5 y 1000 caracteres")
    return valor


def mantener(db: Session, cronograma_id: int, comentario: str, actor: Usuario,
             contexto: ContextoPeticion | None = None) -> dict:
    crono = obtener(db, cronograma_id, actor, EDITORES, bloquear=True)
    _estado(crono, (EstadoCronograma.correccion_solicitada,))
    comentario = _texto(comentario, "El comentario")
    crono.estado = (EstadoCronograma.visto if crono.visto_version_id == crono.version_publicada_id
                    else EstadoCronograma.publicado)
    _limpiar_solicitud(crono)
    _evento(db, crono, crono.version_publicada_id, actor, TipoEventoCronograma.correccion_mantenida, comentario=comentario)
    _auditar(db, crono, actor, "mantener_version", contexto,
             {"version_id": crono.version_publicada_id, "comentario": comentario})
    _correo(db, crono, repo.version(db, crono.version_publicada_id), actor, "correccion_mantenida",
            (RolUsuario.subgerente,), comentario=comentario)
    return _terminar(db, crono, actor)


def eventos(db: Session, cronograma_id: int, actor: Usuario) -> list[dict]:
    crono = obtener(db, cronograma_id, actor, LECTORES)
    return repo.eventos(db, crono.id)


def datos_campo(db: Session, cronograma_id: int, dias: int, actor: Usuario) -> list[dict]:
    crono = obtener(db, cronograma_id, actor, LECTORES)
    if not 1 <= dias <= 14:
        raise DatosInvalidos("Los días deben estar entre 1 y 14")
    modulo = db.get(Modulo, crono.modulo_id)
    return repo.datos_campo(db, modulo.fundo_id, crono.fecha - dt.timedelta(days=dias), crono.fecha)


def eliminar(db: Session, cronograma_id: int, motivo: str, lock_version: int, actor: Usuario,
             contexto: ContextoPeticion | None = None) -> dict:
    """Retira un cronograma de la operación; la transacción la confirma DbSesion."""
    crono = obtener(db, cronograma_id, actor, EDITORES, bloquear=True)
    _lock(crono, lock_version)
    motivo = motivo.strip()
    if not 3 <= len(motivo) <= 500:
        raise DatosInvalidos("El motivo debe tener entre 3 y 500 caracteres")
    versiones = repo.bloquear_versiones(db, crono.id)
    detalle = {
        "modulo_id": crono.modulo_id, "modulo": db.get(Modulo, crono.modulo_id).codigo,
        "fecha": crono.fecha.isoformat(), "motivo": motivo,
        "versiones": sorted(v.numero for v in versiones),
    }
    salida = {"accion": "eliminado", "cronograma_id": crono.id, "fecha": crono.fecha, "avisos": []}
    nunca_publicado = (crono.version_publicada_id is None and crono.num_publicaciones == 0
                       and all(v.publicada_at is None for v in versiones))
    if nunca_publicado and not repo.tiene_referencias_externas(db, crono.id):
        _auditar(db, crono, actor, "eliminar_cronograma", contexto, detalle)
        db.flush()  # La auditoría no tiene FK al cronograma y sobrevive al borrado.
        repo.borrar(db, crono.id)
    else:
        ids = {v.id for v in versiones}
        retirados = []
        # Mismo orden de candados que visto/publicar y edición manual: cronograma, turno-día.
        for turno in sorted(repo_riego.turnos_de_modulo(db, crono.modulo_id), key=lambda t: t.id):
            vigente = repo_riego.bloquear_turno_dia(db, turno.id, crono.fecha)
            if vigente is None:
                continue
            if (vigente.estado == EstadoRiego.provisional and vigente.origen == OrigenRiego.cronograma
                    and vigente.cronograma_version_id in ids):
                retirados.append(vigente.id)
            else:
                causa = ("riego aplicado" if vigente.estado == EstadoRiego.aplicado else
                         "riego provisional manual" if vigente.origen == OrigenRiego.manual else
                         "riego provisional de otro cronograma" if vigente.origen == OrigenRiego.cronograma else
                         "riego provisional de otro origen")
                salida["avisos"].append(f"{turno.codigo}: {causa}; se conservó")
        # No se crea una versión «sin riego»: debe quedar sin registro vigente.
        repo_riego.dejar_de_ser_vigentes(db, retirados)
        crono.anulado_at, crono.anulado_por, crono.anulado_motivo = ahora_utc(), actor.id, motivo
        crono.lock_version += 1
        detalle |= {"registros_retirados": retirados, "avisos": salida["avisos"]}
        _evento(db, crono, crono.version_publicada_id or crono.borrador_version_id, actor,
                TipoEventoCronograma.anulado, comentario=motivo, detalle=detalle)
        _auditar(db, crono, actor, "anular_cronograma", contexto, detalle)
        salida["accion"] = "anulado"
    db.flush()
    return salida
