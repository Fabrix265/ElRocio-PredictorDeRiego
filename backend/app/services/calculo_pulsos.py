"""Riego por pulsos: la lógica de la planilla «MODELO RIEGO POR PULSOS – PALTO» en el backend.

Entrada: los m³/ha que el modelo predice para cada turno en el día (agua **aplicada**, como la
miden los caudalímetros: ya incluye las pérdidas). Salida: n° de pulsos (ciclos), m³/ha y
duración de cada pulso, y hora de inicio y fin de cada uno.

Correspondencia con la planilla (hoja «PULSOS PALTO»):

- Suelo: volumen explorado K8, agua útil K11, agua disponible (AD) K12.
- Sistema: capacidad de riego CR S14 (m³/ha/h), diámetro de bulbo S15.
- Agotamiento por pulso δ: el de la fase (O18:U18) o, con «δ operativo automático» (S60), el menor
  entre ese y el máximo que cabe en un bloque de 3 h (S62). Volumen del pulso J19 = AD·δ/Ea y
  tiempo L19 = J19/CR·60.
- La ETo ya no se ingresa: la «ETr equivalente» del día es m³/ha × Ea / 10 (mm), y con ella se
  elige la curva de aplicación por hora (S49/S55) con los umbrales E16/F16 y el modo de ventana J16.
- Bloques de 3 h desde las 03:00 (filas 23–40): m³/ha del bloque = total × % de la curva,
  pulsos teóricos = m³/ha del bloque / volumen del pulso (columna I) y «Pulso/Turno Ajustado» con
  el redondeo acumulado de la columna J. Converge si los pulsos de todos los turnos caben en el
  tiempo útil del bloque (columna R).

Diferencias deliberadas con la planilla (documentadas en ``detalle["reglas"]``):

- Cada turno tiene su propio total (el modelo predice por turno); la convergencia suma los pulsos
  de todos los turnos en cada bloque.
- Con ``ajustar_pulso_al_total`` el volumen de cada pulso es total / n° de pulsos, para que el día
  sume exactamente lo que dijo el modelo (la planilla deja el pulso fijo y reporta la «Variación»).
- Si el redondeo deja 0 pulsos con un total > 0, se programa 1 pulso en el bloque de mayor %.
- El horario (que la planilla no calcula): en cada bloque los turnos riegan uno tras otro
  (TE01, TE02, …, y otra vuelta si alguno tiene más de un pulso), con el reposo repartido parejo.

Este módulo no toca la base de datos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

HORA_PRIMER_BLOQUE = 3
HORAS_BLOQUE = 3
NUM_BLOQUES = 6  # 03–06, 06–09, 09–12, 12–15, 15–18, 18–21
HORAS_VENTANA = tuple(range(HORA_PRIMER_BLOQUE, HORA_PRIMER_BLOQUE + HORAS_BLOQUE * NUM_BLOQUES))
MAX_PULSOS_TURNO = 12
CURVAS = ("1", "2", "3")
MODOS_VENTANA = ("automatico_con_respaldo", "automatico", "curva_1", "curva_2", "curva_3")
FASES = ("Vegetativo", "Floración", "Cuajado", "Crecimiento de fruta", "Maduración", "Cosecha")
EPS = 1e-9


@dataclass(frozen=True)
class Parametros:
    """Datos fijos del módulo (los de la planilla). Fracciones en 0–1, no en %."""

    capacidad_campo: float
    punto_marchitez: float
    agotamiento_maximo: float
    infiltracion_basica_mmh: float
    ancho_humedo_m: float
    profundidad_raices_m: float
    diametro_bulbo_m: float | None  # None = nominal (= distancia entre goteros)
    distancia_hileras_m: float
    distancia_plantas_m: float
    mangueras_por_hilera: int
    separacion_mangueras_m: float
    distancia_goteros_m: float
    caudal_gotero_lh: float
    reposo_min_por_hora: float
    eficiencia_aplicacion: float
    fase_fenologica: str
    agotamiento_por_fase: dict[str, float]
    agotamiento_automatico: bool
    umbral_etr_1: float
    umbral_etr_2: float
    modo_ventana: str
    curvas: dict[str, dict[int, float]]  # "1"/"2"/"3" -> hora -> % (suma 100)
    ajustar_pulso_al_total: bool = True


@dataclass(frozen=True)
class Derivados:
    diametro_bulbo_m: float
    ancho_bulbos_m: float
    franja_continua: bool
    ancho_efectivo_m: float
    volumen_explorado_m3ha: float
    agua_util: float
    agua_disponible_m3ha: float
    capacidad_riego_m3hah: float
    intensidad_mmh: float
    plantas_ha: float
    goteros_ha: float
    agotamiento_fase: float
    agotamiento_max_bloque: float
    agotamiento_operativo: float
    amortiguacion_m3ha: float
    volumen_pulso_m3ha: float
    minutos_pulso: float

    @property
    def min_por_m3ha(self) -> float:
        return 60.0 / self.capacidad_riego_m3hah


@dataclass
class Bloque:
    indice: int
    inicio_min: int   # minutos desde las 00:00
    fin_min: int
    horas: int        # horas del bloque dentro de la ventana de la curva
    porcentaje: float


@dataclass
class CicloPulso:
    ciclo: int
    riego_m3ha: float
    riego_m3: float
    duracion_min: float
    inicio_min: float
    fin_min: float
    hora_inicio: str
    hora_fin: str
    fin_dia_siguiente: bool

    def como_dict(self) -> dict[str, Any]:
        return {
            "ciclo": self.ciclo, "riego_m3ha": self.riego_m3ha, "riego_m3": self.riego_m3,
            "duracion_min": self.duracion_min, "inicio_min": self.inicio_min, "fin_min": self.fin_min,
            "hora_inicio": self.hora_inicio, "hora_fin": self.hora_fin,
            "fin_dia_siguiente": self.fin_dia_siguiente,
            "m3ha_p10": None, "m3ha_p90": None, "duracion_p10": None, "duracion_p90": None,
            "inicio_desde_min": None, "inicio_hasta_min": None,
        }


@dataclass
class PlanTurno:
    turno: str
    m3ha_modelo: float
    area_ha: float
    teoricos: list[float]
    pulsos_por_bloque: list[int]
    volumen_pulso_m3ha: float
    minutos_pulso: float
    ciclos: list[CicloPulso] = field(default_factory=list)

    @property
    def n_ciclos(self) -> int:
        return sum(self.pulsos_por_bloque)


@dataclass
class PlanPulsos:
    derivados: Derivados
    etr_equivalente_mm: float
    curva_propuesta: str
    curva: str
    motivo: str
    bloques: list[Bloque]
    turnos: dict[str, PlanTurno]
    minutos_riego_bloque: list[float]
    minutos_utiles_bloque: list[float]
    avisos: list[str]

    @property
    def converge(self) -> bool:
        return all(r <= u + EPS for r, u in zip(self.minutos_riego_bloque, self.minutos_utiles_bloque))


# --- Utilidades --------------------------------------------------------------------

def redondear(x: float) -> int:
    """ROUND de Excel (mitades hacia arriba), no el redondeo bancario de Python."""
    return int(math.floor(x + 0.5 + EPS))


def hhmm(minutos: float) -> str:
    """Minutos desde las 00:00 → "HH:MM" (pasada la medianoche vuelve a 00:00)."""
    total = int(round(minutos)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def ventana(curva: dict[int, float]) -> tuple[int, int] | None:
    """Primera hora y hora final (exclusiva) con % > 0 de la curva."""
    horas = [h for h, p in curva.items() if p > EPS]
    return (min(horas), max(horas) + 1) if horas else None


def bloques_de(curva: dict[int, float]) -> list[Bloque]:
    """Los 6 bloques de 3 h; ``horas`` = horas del bloque dentro de la ventana de la curva."""
    v = ventana(curva) or (0, 0)
    salida = []
    for i in range(NUM_BLOQUES):
        inicio_h = HORA_PRIMER_BLOQUE + i * HORAS_BLOQUE
        horas = [h for h in range(inicio_h, inicio_h + HORAS_BLOQUE) if v[0] <= h < v[1]]
        salida.append(Bloque(
            indice=i,
            inicio_min=(horas[0] if horas else inicio_h) * 60,
            fin_min=((horas[-1] + 1) if horas else inicio_h) * 60,
            horas=len(horas),
            porcentaje=sum(curva.get(h, 0.0) for h in range(inicio_h, inicio_h + HORAS_BLOQUE)),
        ))
    return salida


# --- Paso 1: derivados del suelo y del sistema (parte superior de la planilla) --------

def derivados(p: Parametros, n_turnos: int) -> Derivados:
    if n_turnos < 1:
        raise ValueError("Se necesita al menos un turno")
    bulbo = p.diametro_bulbo_m if p.diametro_bulbo_m else p.distancia_goteros_m
    continua = p.distancia_goteros_m <= bulbo
    if continua:
        ancho_bulbos = (p.mangueras_por_hilera - 1) * min(p.separacion_mangueras_m, bulbo) + bulbo
        intensidad = p.caudal_gotero_lh / (p.distancia_goteros_m * bulbo)
    else:
        ancho_bulbos = p.mangueras_por_hilera * math.pi * bulbo ** 2 / 4 / p.distancia_goteros_m
        intensidad = p.caudal_gotero_lh / (math.pi * bulbo ** 2 / 4)
    ancho_efectivo = min(p.ancho_humedo_m, ancho_bulbos)
    volumen = 10000.0 / p.distancia_hileras_m * ancho_efectivo * p.profundidad_raices_m
    agua_util = p.capacidad_campo - p.punto_marchitez
    ad = agua_util * volumen
    cr = p.mangueras_por_hilera * p.caudal_gotero_lh / (p.distancia_hileras_m * p.distancia_goteros_m) * 10.0
    delta_fase = p.agotamiento_por_fase[p.fase_fenologica]
    # S62: el δ máximo con el que los pulsos de todos los turnos caben en un bloque de 3 h.
    delta_bloque = HORAS_BLOQUE * (60.0 - p.reposo_min_por_hora) / n_turnos * cr / 60.0 \
        * p.eficiencia_aplicacion / ad
    delta = min(delta_fase, delta_bloque) if p.agotamiento_automatico else delta_fase
    volumen_pulso = ad * delta / p.eficiencia_aplicacion
    return Derivados(
        diametro_bulbo_m=bulbo, ancho_bulbos_m=ancho_bulbos, franja_continua=continua,
        ancho_efectivo_m=ancho_efectivo, volumen_explorado_m3ha=volumen, agua_util=agua_util,
        agua_disponible_m3ha=ad, capacidad_riego_m3hah=cr, intensidad_mmh=intensidad,
        plantas_ha=10000.0 / (p.distancia_hileras_m * p.distancia_plantas_m),
        goteros_ha=10000.0 / p.distancia_hileras_m * p.mangueras_por_hilera / p.distancia_goteros_m,
        agotamiento_fase=delta_fase, agotamiento_max_bloque=delta_bloque, agotamiento_operativo=delta,
        amortiguacion_m3ha=ad * (p.agotamiento_maximo - delta),
        volumen_pulso_m3ha=volumen_pulso, minutos_pulso=volumen_pulso / cr * 60.0,
    )


# --- Paso 2: pulsos por bloque de un turno (columnas G–J) ----------------------------

def pulsos_por_bloque(total_m3ha: float, bloques: list[Bloque], volumen_pulso: float) -> tuple[list[float], list[int]]:
    """Pulsos teóricos (I) y ajustados con redondeo acumulado (J) de un turno."""
    teoricos = [total_m3ha * b.porcentaje / 100.0 / volumen_pulso for b in bloques]
    acumulado, previo, ajustados = 0.0, 0, []
    for t in teoricos:
        acumulado += t
        actual = redondear(acumulado)
        ajustados.append(actual - previo)
        previo = actual
    if total_m3ha > EPS and sum(ajustados) == 0:
        mayor = max(range(len(bloques)), key=lambda i: (bloques[i].porcentaje, -i))
        ajustados[mayor] = 1
    return teoricos, ajustados


def repartir_n(n: int, bloques: list[Bloque]) -> list[int]:
    """``n`` pulsos repartidos según el % de cada bloque (mismo redondeo acumulado)."""
    acumulado, previo, salida = 0.0, 0, []
    for b in bloques:
        acumulado += n * b.porcentaje / 100.0
        actual = redondear(acumulado)
        salida.append(actual - previo)
        previo = actual
    faltan = n - sum(salida)
    if faltan > 0:  # solo si la curva no suma 100
        mayor = max(range(len(bloques)), key=lambda i: bloques[i].porcentaje)
        salida[mayor] += faltan
    return salida


# --- Paso 3: elegir la curva (S49 / S55) ------------------------------------------------

def curva_por_umbral(etr_mm: float, p: Parametros) -> str:
    if etr_mm < p.umbral_etr_1:
        return "1"
    return "2" if etr_mm <= p.umbral_etr_2 else "3"


def _minutos_utiles(bloques: list[Bloque], p: Parametros) -> list[float]:
    return [b.horas * (60.0 - p.reposo_min_por_hora) for b in bloques]


def _armar_turnos(totales: dict[str, float], areas: dict[str, float], bloques: list[Bloque],
                  d: Derivados, p: Parametros, forzados: dict[str, int] | None = None) -> dict[str, PlanTurno]:
    turnos = {}
    for turno, total in totales.items():
        teoricos, ajustados = pulsos_por_bloque(total, bloques, d.volumen_pulso_m3ha)
        if forzados and turno in forzados:
            ajustados = repartir_n(forzados[turno], bloques)
        n = sum(ajustados)
        volumen = (total / n) if (n and (p.ajustar_pulso_al_total or (forzados and turno in forzados))) \
            else d.volumen_pulso_m3ha
        turnos[turno] = PlanTurno(
            turno=turno, m3ha_modelo=total, area_ha=areas.get(turno, 0.0), teoricos=teoricos,
            pulsos_por_bloque=ajustados, volumen_pulso_m3ha=volumen,
            minutos_pulso=volumen * d.min_por_m3ha,
        )
    return turnos


def _minutos_riego(turnos: dict[str, PlanTurno]) -> list[float]:
    return [sum(t.pulsos_por_bloque[i] * t.minutos_pulso for t in turnos.values()) for i in range(NUM_BLOQUES)]


def _converge(turnos: dict[str, PlanTurno], bloques: list[Bloque], p: Parametros) -> bool:
    return all(r <= u + EPS for r, u in zip(_minutos_riego(turnos), _minutos_utiles(bloques, p)))


# --- Paso 4: horario (no está en la planilla) ------------------------------------------

def _horario(turnos: dict[str, PlanTurno], bloques: list[Bloque]) -> None:
    """En cada bloque, los turnos riegan uno tras otro en su orden, con el reposo repartido parejo
    entre pulsos. Si no caben, siguen sin reposo y pasan al bloque siguiente (aviso aparte)."""
    for t in turnos.values():
        t.ciclos = []
    cursor = 0.0
    for b in bloques:
        secuencia = []
        maximo = max((t.pulsos_por_bloque[b.indice] for t in turnos.values()), default=0)
        for vuelta in range(maximo):
            secuencia += [t for t in turnos.values() if t.pulsos_por_bloque[b.indice] > vuelta]
        if not secuencia:
            continue
        activos = sum(t.minutos_pulso for t in secuencia)
        reposo = max(0.0, ((b.fin_min - b.inicio_min) - activos) / len(secuencia))
        cursor = max(cursor, float(b.inicio_min))
        for t in secuencia:
            inicio = round(cursor, 1)
            duracion = round(t.minutos_pulso, 1)
            fin = round(inicio + duracion, 1)
            m3ha = round(t.volumen_pulso_m3ha, 2)
            t.ciclos.append(CicloPulso(
                ciclo=len(t.ciclos) + 1, riego_m3ha=m3ha, riego_m3=round(m3ha * t.area_ha, 1),
                duracion_min=duracion, inicio_min=inicio, fin_min=fin,
                hora_inicio=hhmm(inicio), hora_fin=hhmm(fin), fin_dia_siguiente=fin >= 1440,
            ))
            cursor += t.minutos_pulso + reposo


# --- Plan completo ----------------------------------------------------------------------

def _motivo(p: Parametros, propuesta: str, elegida: str, etr: float) -> str:
    if p.modo_ventana.startswith("curva_"):
        return f"Curva {elegida} fijada en los parámetros"
    rango = (f"< {p.umbral_etr_1:g}" if propuesta == "1" else
             f"{p.umbral_etr_1:g}–{p.umbral_etr_2:g}" if propuesta == "2" else f"> {p.umbral_etr_2:g}")
    texto = f"ETr equivalente {etr:.2f} mm → curva {propuesta} ({rango})"
    if elegida != propuesta:
        texto += f"; no converge, se usa la curva {elegida}"
    return texto


def calcular(totales: dict[str, float], areas: dict[str, float], p: Parametros,
             forzados: dict[str, int] | None = None, curva_fija: str | None = None) -> PlanPulsos:
    """Plan por pulsos del módulo para un día.

    ``totales``: turno → m³/ha del modelo (en el orden de riego). ``areas``: turno → ha.
    ``forzados``: turno → n° de pulsos (alternativas al editar). ``curva_fija``: no vuelve a elegir.
    """
    if not totales:
        raise ValueError("No hay turnos que planificar")
    d = derivados(p, len(totales))
    promedio = sum(totales.values()) / len(totales)
    etr = promedio * p.eficiencia_aplicacion / 10.0
    propuesta = curva_por_umbral(etr, p)
    if curva_fija:
        candidatas = [curva_fija]
    elif p.modo_ventana.startswith("curva_"):
        candidatas = [p.modo_ventana.removeprefix("curva_")]
    elif p.modo_ventana == "automatico":
        candidatas = [propuesta]
    else:  # automático con respaldo: 1 → 2 → 3
        candidatas = list(CURVAS[CURVAS.index(propuesta):])
    for curva in candidatas:
        bloques = bloques_de(p.curvas[curva])
        turnos = _armar_turnos(totales, areas, bloques, d, p, forzados)
        if _converge(turnos, bloques, p):
            break
    _horario(turnos, bloques)
    plan = PlanPulsos(
        derivados=d, etr_equivalente_mm=etr, curva_propuesta=propuesta, curva=curva,
        motivo=_motivo(p, propuesta, curva, etr), bloques=bloques, turnos=turnos,
        minutos_riego_bloque=_minutos_riego(turnos), minutos_utiles_bloque=_minutos_utiles(bloques, p),
        avisos=[],
    )
    for b, riego, util in zip(bloques, plan.minutos_riego_bloque, plan.minutos_utiles_bloque):
        if riego > util + EPS:
            plan.avisos.append(
                f"No converge el bloque {hhmm(b.inicio_min)}–{hhmm(b.fin_min)}: faltan "
                f"{math.ceil(riego - util)} min (los pulsos se corren al bloque siguiente)."
            )
    if d.intensidad_mmh > p.infiltracion_basica_mmh:
        plan.avisos.append(
            f"La intensidad del gotero ({d.intensidad_mmh:.1f} mm/h) supera la infiltración básica "
            f"del suelo ({p.infiltracion_basica_mmh:g} mm/h)."
        )
    if d.ancho_bulbos_m < p.ancho_humedo_m - 0.005:
        plan.avisos.append(
            f"Los bulbos mojan {d.ancho_bulbos_m:.2f} m, menos que el ancho efectivo indicado "
            f"({p.ancho_humedo_m:g} m): se usa {d.ancho_bulbos_m:.2f} m."
        )
    for t in turnos.values():
        if t.n_ciclos > MAX_PULSOS_TURNO:
            plan.avisos.append(f"{t.turno}: {t.n_ciclos} pulsos superan el máximo editable ({MAX_PULSOS_TURNO}).")
    return plan


def alternativas(plan: PlanPulsos, totales: dict[str, float], areas: dict[str, float], p: Parametros,
                 maximo: int = MAX_PULSOS_TURNO) -> dict[str, dict[int, list[dict[str, Any]]]]:
    """Para cada turno, el plan con n = 1..``maximo`` pulsos (los demás turnos como en ``plan``),
    con la curva ya elegida. Es lo que usa el editor al cambiar el n° de ciclos."""
    salida: dict[str, dict[int, list[dict[str, Any]]]] = {}
    base = {t: tp.n_ciclos for t, tp in plan.turnos.items()}
    for turno in totales:
        salida[turno] = {}
        for n in range(1, maximo + 1):
            forzados = {**base, turno: n}
            otro = calcular(totales, areas, p, forzados=forzados, curva_fija=plan.curva)
            salida[turno][n] = [c.como_dict() for c in otro.turnos[turno].ciclos]
    return salida


def detalle(plan: PlanPulsos, p: Parametros) -> dict[str, Any]:
    """Resumen JSON del cálculo (se guarda con la versión del cronograma y se muestra al revisar)."""
    d = plan.derivados
    return {
        "metodo": "pulsos",
        "curva": plan.curva,
        "curva_propuesta": plan.curva_propuesta,
        "motivo": plan.motivo,
        "etr_equivalente_mm": round(plan.etr_equivalente_mm, 2),
        "ventana": [hhmm(min(b.inicio_min for b in plan.bloques if b.horas)),
                    hhmm(max(b.fin_min for b in plan.bloques if b.horas))]
        if any(b.horas for b in plan.bloques) else None,
        "converge": plan.converge,
        "fase_fenologica": p.fase_fenologica,
        "derivados": {
            "volumen_explorado_m3ha": round(d.volumen_explorado_m3ha, 1),
            "agua_disponible_m3ha": round(d.agua_disponible_m3ha, 2),
            "capacidad_riego_m3hah": round(d.capacidad_riego_m3hah, 2),
            "agotamiento_fase": d.agotamiento_fase,
            "agotamiento_max_bloque": round(d.agotamiento_max_bloque, 4),
            "agotamiento_operativo": round(d.agotamiento_operativo, 4),
            "volumen_pulso_m3ha": round(d.volumen_pulso_m3ha, 2),
            "minutos_pulso": round(d.minutos_pulso, 1),
            "intensidad_mmh": round(d.intensidad_mmh, 1),
        },
        "bloques": [{
            "inicio": hhmm(HORA_PRIMER_BLOQUE * 60 + b.indice * HORAS_BLOQUE * 60),
            "fin": hhmm(HORA_PRIMER_BLOQUE * 60 + (b.indice + 1) * HORAS_BLOQUE * 60),
            "horas": b.horas, "porcentaje": round(b.porcentaje, 2),
            "minutos_utiles": round(u, 1), "minutos_riego": round(r, 1), "reposo_min": round(u - r, 1),
            "converge": r <= u + EPS,
        } for b, r, u in zip(plan.bloques, plan.minutos_riego_bloque, plan.minutos_utiles_bloque)],
        "turnos": [{
            "turno": t.turno, "m3ha_modelo": round(t.m3ha_modelo, 2),
            "pulsos_teoricos": [round(x, 2) for x in t.teoricos],
            "pulsos_por_bloque": t.pulsos_por_bloque, "n_ciclos": t.n_ciclos,
            "m3ha_pulso": round(t.volumen_pulso_m3ha, 2), "minutos_pulso": round(t.minutos_pulso, 1),
            "m3ha_programado": round(sum(c.riego_m3ha for c in t.ciclos), 2),
        } for t in plan.turnos.values()],
        "avisos": plan.avisos,
        "reglas": {
            "ajustar_pulso_al_total": p.ajustar_pulso_al_total,
            "orden_turnos": "uno tras otro en cada bloque, reposo repartido parejo",
        },
    }
