"""Reportes de F5: agua aplicada vs propuesta, KPIs del Dashboard, exportación del cronograma
(PDF y Excel) y CSV de refinamiento (§2.4).

Visibilidad: el programador ve solo lo publicado y nunca la propuesta del modelo (§4).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any

from sqlalchemy.orm import Session

from app.core.errores import DatosInvalidos, NoEncontrado
from app.core.tiempo import hoy_lima
from app.models import Cronograma, CronogramaEvento, CronogramaVersion, Fundo, Modulo, Usuario
from app.models.enums import OrigenVersion, RolUsuario, TipoEventoCronograma
from app.repositories import cronogramas as repo_crono
from app.repositories import datos_series as repo_series
from app.repositories import reportes as repo
from app.repositories import riego as repo_riego
from app.services import auditoria_service, cronograma_service, datos_service
from app.services.contexto import ContextoPeticion

DIAS_AGUA = 14
MAX_DIAS_AGUA = 92
MAX_DIAS_REFINAMIENTO = 366
ORIGENES_MODELO = (OrigenVersion.modelo, OrigenVersion.regenerado)
CARACTERES_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _es_programador(usuario: Usuario) -> bool:
    return usuario.rol == RolUsuario.programador


def _por_cronograma(versiones: list[CronogramaVersion]) -> dict[int, list[CronogramaVersion]]:
    salida: dict[int, list[CronogramaVersion]] = {}
    for v in versiones:
        salida.setdefault(v.cronograma_id, []).append(v)
    return salida


def _modelo_mas_reciente(versiones: list[CronogramaVersion]) -> CronogramaVersion | None:
    del_modelo = [v for v in versiones if v.origen in ORIGENES_MODELO]
    return del_modelo[-1] if del_modelo else None


def _totales_por_turno(version: CronogramaVersion | None) -> dict[int, tuple[float, float]]:
    """``turno_id -> (m3/ha, m3)`` de una versión."""
    if version is None:
        return {}
    salida: dict[int, list[float]] = {}
    for c in version.ciclos:
        acum = salida.setdefault(c.turno_id, [0.0, 0.0])
        acum[0] += c.riego_m3ha
        acum[1] += c.riego_m3
    return {t: (round(a, 2), round(b, 1)) for t, (a, b) in salida.items()}


# --- Agua aplicada vs propuesta (KPI 1 y Datos de campo) -----------------------------

def agua(db: Session, modulo_id: int, desde: dt.date | None, hasta: dt.date | None,
         usuario: Usuario) -> dict[str, Any]:
    modulo = datos_service.modulo_o_404(db, modulo_id)
    datos_service.validar_fechas(desde, hasta)
    hasta = hasta or hoy_lima() - dt.timedelta(days=1)
    desde = desde or hasta - dt.timedelta(days=DIAS_AGUA - 1)
    if desde > hasta:
        raise DatosInvalidos("«desde» debe ser anterior o igual a «hasta»")
    if (hasta - desde).days + 1 > MAX_DIAS_AGUA:
        raise DatosInvalidos(f"El rango no puede superar {MAX_DIAS_AGUA} días")
    programador = _es_programador(usuario)

    turnos = repo_riego.turnos_de_modulo(db, modulo.id)
    registros = {(r.turno_id, r.fecha): r for r in
                 repo_riego.vigentes(db, modulo.id, desde=desde, hasta=hasta + dt.timedelta(days=1))}
    cronos = {c.fecha: c for c in repo.cronogramas_rango(db, modulo.id, desde, hasta)}
    versiones = _por_cronograma(repo.versiones_de(db, [c.id for c in cronos.values()]))

    dias = []
    fecha = desde
    while fecha <= hasta:
        crono = cronos.get(fecha)
        lista = versiones.get(crono.id, []) if crono else []
        por_id = {v.id: v for v in lista}
        if crono is None:
            propuesta = None
        elif programador:
            propuesta = por_id.get(crono.version_publicada_id)
        else:
            propuesta = por_id.get(crono.version_publicada_id) or por_id.get(crono.borrador_version_id)
        modelo = None if programador else _modelo_mas_reciente(lista)
        prop, mod = _totales_por_turno(propuesta), _totales_por_turno(modelo)
        filas = []
        for t in turnos:
            r = registros.get((t.id, fecha))
            aplicado_m3ha = aplicado_m3 = None
            if r is not None:
                aplicado_m3ha = round(sum(c.riego_m3ha or 0 for c in r.ciclos), 2)
                aplicado_m3 = round(sum(c.riego_m3 or 0 for c in r.ciclos), 1)
            filas.append({
                "turno_id": t.id, "turno_codigo": t.codigo, "area_ha": t.area_ha,
                "aplicado_m3ha": aplicado_m3ha, "aplicado_m3": aplicado_m3,
                "estado_riego": r.estado.value if r else None, "sin_riego": bool(r and r.sin_riego),
                "propuesto_m3ha": prop.get(t.id, (None, None))[0], "propuesto_m3": prop.get(t.id, (None, None))[1],
                "modelo_m3ha": mod.get(t.id, (None, None))[0], "modelo_m3": mod.get(t.id, (None, None))[1],
            })
        dias.append({"fecha": fecha, "cronograma_id": crono.id if crono and (propuesta or not programador) else None,
                     "turnos": filas})
        fecha += dt.timedelta(days=1)
    return {"modulo_id": modulo.id, "desde": desde, "hasta": hasta, "dias": dias,
            "con_modelo": not programador}


def _suma(valores: list[float | None]) -> float | None:
    reales = [v for v in valores if v is not None]
    return sum(reales) if reales else None


# --- Dashboard -----------------------------------------------------------------------

def dashboard(db: Session, modulo_id: int, usuario: Usuario) -> dict[str, Any]:
    """KPIs de ayer y pronóstico (frescura y «Hoy y mañana» tienen sus propios endpoints)."""
    modulo = datos_service.modulo_o_404(db, modulo_id)
    hoy = hoy_lima()
    ayer = hoy - dt.timedelta(days=1)
    dia = agua(db, modulo.id, ayer, ayer, usuario)["dias"][0]
    area = sum(t["area_ha"] for t in dia["turnos"] if t["aplicado_m3"] is not None) or None
    aplicado_m3 = _suma([t["aplicado_m3"] for t in dia["turnos"]])
    modelo_m3 = _suma([t["modelo_m3"] for t in dia["turnos"] if t["aplicado_m3"] is not None])
    ambiente = repo_series.ambiente(db, modulo.fundo_id, ayer, ayer)
    amb = ambiente[0] if ambiente else None
    manana = repo_crono.por_fecha(db, modulo.id, hoy + dt.timedelta(days=1))
    if manana is not None and _es_programador(usuario) and manana.version_publicada_id is None:
        manana = None
    pronostico = datos_service.serie_pronostico(db, desde=hoy, hasta=hoy + dt.timedelta(days=4), capturado=None)
    return {
        "modulo_id": modulo.id, "fecha": hoy, "ayer": ayer,
        "ultimo_riego_fecha": repo_riego.ultima_fecha_vigente(db, modulo.id, ayer),
        "agua_aplicada_m3ha": round(aplicado_m3 / area, 1) if aplicado_m3 is not None and area else None,
        "agua_aplicada_m3": round(aplicado_m3, 0) if aplicado_m3 is not None else None,
        "turnos_con_riego": sum(1 for t in dia["turnos"] if t["aplicado_m3"] is not None),
        "turnos_total": len(dia["turnos"]),
        # El programador no ve la propuesta del modelo (§4).
        "aplicado_vs_modelo_pct": (round(aplicado_m3 / modelo_m3 * 100, 0)
                                   if not _es_programador(usuario) and aplicado_m3 is not None and modelo_m3 else None),
        "mds_um": amb.mds_contraccion_um if amb else None,
        "eto_mm": amb.eto_mm if amb else None,
        "estado_manana": manana.estado.value if manana else None,
        "cronograma_manana_id": manana.id if manana else None,
        "pronostico": pronostico,
    }


# --- Exportar un cronograma (PDF / Excel) ------------------------------------------

def _version_exportable(db: Session, crono: Cronograma, usuario: Usuario) -> CronogramaVersion:
    if _es_programador(usuario):
        version_id = crono.version_publicada_id  # el programador exporta siempre la publicada
    else:
        version_id = crono.borrador_version_id or crono.version_publicada_id
    version = repo_crono.version(db, version_id)
    if version is None:
        raise NoEncontrado("Cronograma no encontrado")
    return version


def _filas_plan(db: Session, version: CronogramaVersion, modulo_id: int, orden: str = "turno") -> list[dict[str, Any]]:
    turnos = {t.id: t for t in repo_riego.turnos_de_modulo(db, modulo_id)}
    filas = []
    def clave(c):
        turno_ciclo = (turnos[c.turno_id].orden if c.turno_id in turnos else 0, c.ciclo)
        return (c.inicio_min, *turno_ciclo) if orden == "hora" else turno_ciclo

    for c in sorted(version.ciclos, key=clave):
        filas.append({
            "turno": turnos[c.turno_id].codigo if c.turno_id in turnos else str(c.turno_id), "ciclo": c.ciclo,
            "inicio": c.hora_inicio, "fin": c.hora_fin + (" (+1)" if c.fin_dia_siguiente else ""),
            "duracion_min": round(c.duracion_min, 1), "m3ha": round(c.riego_m3ha, 2), "m3": round(c.riego_m3, 1),
        })
    return filas


def exportar(db: Session, cronograma_id: int, formato: str, usuario: Usuario,
             contexto: ContextoPeticion | None = None, *, orden: str = "turno") -> tuple[bytes, str, str]:
    """``(contenido, media_type, nombre_archivo)``; audita y deja el evento ``exportado``."""
    crono = repo_crono.obtener(db, cronograma_id)
    if crono is None:
        raise NoEncontrado("Cronograma no encontrado")
    cronograma_service._visible(crono, usuario)
    version = _version_exportable(db, crono, usuario)
    modulo = db.get(Modulo, crono.modulo_id)
    fundo = db.get(Fundo, modulo.fundo_id)
    filas = _filas_plan(db, version, modulo.id, orden)
    meta = {
        "fundo": fundo.nombre if fundo else "", "modulo": modulo.codigo, "fecha": crono.fecha,
        "estado": crono.estado.value, "version": version.numero, "origen": version.origen.value,
        "publicada": version.publicada_at is not None,
        "marcas": [m for m, activa in (("Preliminar", version.preliminar), ("Datos incompletos", version.datos_incompletos),
                                       ("Regenerado", version.origen == OrigenVersion.regenerado)) if activa],
        "usuario": usuario.username, "orden": orden,
    }
    nombre = f"cronograma_{modulo.codigo}_{crono.fecha:%Y-%m-%d}_v{version.numero}"
    if formato == "pdf":
        from app.services.exportar_pdf import plan_pdf

        contenido, media, nombre = plan_pdf(meta, filas), "application/pdf", f"{nombre}.pdf"
    elif formato == "xlsx":
        contenido = _plan_xlsx(meta, filas)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        nombre = f"{nombre}.xlsx"
    else:
        raise DatosInvalidos("Formato desconocido: usa pdf o xlsx.")
    db.add(CronogramaEvento(cronograma_id=crono.id, version_id=version.id, usuario_id=usuario.id,
                            tipo=TipoEventoCronograma.exportado, detalle={"formato": formato, "orden": orden}))
    auditoria_service.registrar(db, accion=f"exportar_{formato}", entidad="cronograma", entidad_id=crono.id,
                                actor=usuario, contexto=contexto, detalle={"version": version.numero})
    db.flush()
    return contenido, media, nombre


ETIQUETA_ESTADO = {"borrador": "Borrador", "publicado": "Publicado", "visto": "Visto",
                   "correccion_solicitada": "Corrección solicitada"}
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def fecha_larga(fecha: dt.date) -> str:
    return f"{DIAS[fecha.weekday()]} {fecha:%d/%m/%Y}"


def _plan_xlsx(meta: dict[str, Any], filas: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Plan"
    verde = PatternFill("solid", fgColor="2A7042")
    hoja.append(["Plan de riego · Grupo El Rocío"])
    hoja["A1"].font = Font(bold=True, size=14, color="1B482C")
    hoja.append([f"{meta['fundo']} · {meta['modulo']} · {fecha_larga(meta['fecha'])}"])
    hoja.append([f"Estado: {ETIQUETA_ESTADO.get(meta['estado'], meta['estado'])} · versión v{meta['version']}"
                 + (f" · {', '.join(meta['marcas'])}" if meta["marcas"] else "")])
    hoja.append([f"Orden: por {meta.get('orden', 'turno')}"])
    cabecera = ["Turno", "Ciclo", "Inicio", "Fin", "Duración (min)", "m³/ha", "m³"]
    hoja.append(cabecera)
    for celda in hoja[5]:
        celda.font, celda.fill = Font(bold=True, color="FFFFFF"), verde
        celda.alignment = Alignment(horizontal="center")
    for f in filas:
        hoja.append([f["turno"], f["ciclo"], f["inicio"], f["fin"], f["duracion_min"], f["m3ha"], f["m3"]])
    total = len(filas) + 5
    hoja.append(["Total", None, None, None, f"=SUM(E6:E{total})", None, f"=SUM(G6:G{total})"])
    for celda in hoja[total + 1]:
        celda.font = Font(bold=True)
    for columna, ancho in zip("ABCDEFG", (10, 8, 10, 12, 16, 10, 10)):
        hoja.column_dimensions[columna].width = ancho
    for fila in hoja.iter_rows(min_row=6, max_row=total, min_col=5, max_col=7):
        fila[0].number_format, fila[1].number_format, fila[2].number_format = "0.0", "0.00", "0.0"
    hoja.freeze_panes = "A6"
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


# --- CSV de refinamiento (§2.4, solo admin) -----------------------------------------

def _texto_seguro(valor: Any) -> Any:
    """Escapa la inyección de fórmulas en CSV (texto que empieza con = + - @ tab o CR)."""
    if isinstance(valor, str) and valor.startswith(CARACTERES_FORMULA):
        return "'" + valor
    return valor


def _ciclos_por_turno(version: CronogramaVersion | None) -> dict[tuple[int, int], Any]:
    return {} if version is None else {(c.turno_id, c.ciclo): c for c in version.ciclos}


def _n_por_turno(version: CronogramaVersion | None) -> dict[int, int]:
    return {} if version is None else {t.turno_id: t.n_ciclos for t in version.turnos}


def refinamiento_csv(db: Session, desde: dt.date | None, hasta: dt.date | None, usuario: Usuario,
                     contexto: ContextoPeticion | None = None) -> tuple[bytes, str]:
    datos_service.validar_fechas(desde, hasta)
    hasta = hasta or hoy_lima()
    desde = desde or hasta - dt.timedelta(days=89)
    if desde > hasta:
        raise DatosInvalidos("«desde» debe ser anterior o igual a «hasta»")
    if (hasta - desde).days + 1 > MAX_DIAS_REFINAMIENTO:
        raise DatosInvalidos(f"El rango no puede superar {MAX_DIAS_REFINAMIENTO} días")

    cronos = repo.cronogramas_todos_modulos(db, desde, hasta)
    versiones = _por_cronograma(repo.versiones_de(db, [c.id for c in cronos]))
    modulos = repo.modulos(db)
    fundos = {m.fundo_id: db.get(Fundo, m.fundo_id) for m in modulos.values()}
    modelos = repo.nombres_modelo(db)
    generaciones = [v.generacion_id for lista in versiones.values() for v in lista if v.generacion_id]
    fotos = repo.fotos(db, generaciones)

    filas: list[dict[str, Any]] = []
    columnas_foto: list[str] = []
    for crono in cronos:
        lista = versiones.get(crono.id, [])
        if not lista:
            continue
        modulo = modulos[crono.modulo_id]
        turnos = {t.id: t for t in repo_riego.turnos_de_modulo(db, modulo.id)}
        por_id = {v.id: v for v in lista}
        v1 = lista[0]
        base = _modelo_mas_reciente(lista)
        final = por_id.get(crono.version_publicada_id)
        correcciones = [v for v in lista if base and v.numero > base.numero and v.origen not in ORIGENES_MODELO]
        motivos = [v.motivo_codigo for v in correcciones if v.motivo_codigo]
        registros = {r.turno_id: r for r in repo_riego.vigentes(
            db, modulo.id, desde=crono.fecha, hasta=crono.fecha + dt.timedelta(days=1))}
        bloques = {"modelo_v1": v1, "modelo_base": base, "final": final}
        ciclos = {k: _ciclos_por_turno(v) for k, v in bloques.items()}
        n_ciclos = {k: _n_por_turno(v) for k, v in bloques.items()}
        claves = sorted({k for d in ciclos.values() for k in d}
                        | {(t, i + 1) for t, r in registros.items() for i in range(len(r.ciclos))})
        for turno_id, ciclo in claves:
            turno = turnos.get(turno_id)
            fila: dict[str, Any] = {
                "Fecha": crono.fecha.isoformat(), "Fundo": fundos[modulo.fundo_id].nombre if fundos.get(modulo.fundo_id) else "",
                "Modulo": modulo.codigo, "Turno": turno.codigo if turno else str(turno_id), "Ciclo": ciclo,
            }
            foto = fotos.get((base.generacion_id, crono.fecha, turno_id)) if base and base.generacion_id else None
            if foto is not None:
                ciclo_foto = next((c for c in (foto.features_ciclo or []) if c.get("Ciclo") == ciclo), {})
                for k, v in {**(foto.features_turno or {}), **ciclo_foto}.items():
                    if k in ("Ciclo",):
                        continue
                    fila[k] = v
                    if k not in columnas_foto:
                        columnas_foto.append(k)
            for bloque in bloques:
                c = ciclos[bloque].get((turno_id, ciclo))
                fila[f"{bloque}_n_ciclos"] = n_ciclos[bloque].get(turno_id)
                fila[f"{bloque}_riego_m3ha"] = c.riego_m3ha if c else None
                fila[f"{bloque}_inicio_min"] = c.inicio_min if c else None
                fila[f"{bloque}_duracion_min"] = c.duracion_min if c else None
            r = registros.get(turno_id)
            ciclos_aplicados = sorted(r.ciclos, key=lambda x: x.inicio_min) if r else []
            ca = ciclos_aplicados[ciclo - 1] if len(ciclos_aplicados) >= ciclo else None
            fila |= {
                "aplicado_n_ciclos": len(ciclos_aplicados) if r else None,
                "aplicado_riego_m3ha": ca.riego_m3ha if ca else None,
                "aplicado_inicio_min": ca.inicio_min if ca else None,
                "aplicado_duracion_min": ca.duracion_min if ca else None,
                "estado_riego": ("sin_riego" if r.sin_riego else r.estado.value) if r else None,
                "motivos": "|".join(motivos), "ultimo_motivo": motivos[-1] if motivos else None,
                "n_correcciones": len(correcciones),
                "preliminar": (final or lista[-1]).preliminar,
                "datos_incompletos": (final or lista[-1]).datos_incompletos,
                "regenerado": any(v.origen == OrigenVersion.regenerado for v in lista),
                "num_versiones": len(lista),
                "modelo_version": modelos.get(base.modelo_version_id) if base else None,
                "anulado": crono.anulado_at is not None,
                "anulado_motivo": crono.anulado_motivo,
            }
            filas.append(fila)

    fijas = ["Fecha", "Fundo", "Modulo", "Turno", "Ciclo"]
    bloques_cols = [f"{b}_{c}" for b in ("modelo_v1", "modelo_base", "final", "aplicado")
                    for c in ("n_ciclos", "riego_m3ha", "inicio_min", "duracion_min")]
    resto = ["estado_riego", "motivos", "ultimo_motivo", "n_correcciones", "preliminar", "datos_incompletos",
             "regenerado", "num_versiones", "modelo_version", "anulado", "anulado_motivo"]
    columnas = fijas + columnas_foto + bloques_cols + resto
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=columnas, extrasaction="ignore", lineterminator="\n")
    escritor.writeheader()
    for fila in filas:
        escritor.writerow({k: _texto_seguro(v) for k, v in fila.items()})
    auditoria_service.registrar(db, accion="exportar_refinamiento", entidad="exportacion", actor=usuario,
                                contexto=contexto, detalle={"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                                                            "filas": len(filas)})
    db.flush()
    nombre = f"refinamiento_{desde:%Y-%m-%d}_{hasta:%Y-%m-%d}.csv"
    # BOM para que Excel abra bien las tildes.
    return ("﻿" + salida.getvalue()).encode("utf-8"), nombre
