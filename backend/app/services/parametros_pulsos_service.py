"""Parámetros del riego por pulsos por módulo: lectura (con lo que se calcula de ellos), validación
y edición auditada. Los valores por defecto son los de la planilla (también en la migración 0006)."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy.orm import Session

from app.core.errores import DatosInvalidos
from app.models import ParametrosPulsos, Usuario
from app.repositories import pulsos as repo
from app.repositories import riego as repo_riego
from app.schemas.pulsos import ParametrosPulsosEntrada
from app.services import auditoria_service, calculo_pulsos, datos_service
from app.services.contexto import ContextoPeticion

CAMPOS = tuple(ParametrosPulsosEntrada.model_fields)

POR_DEFECTO: dict[str, Any] = {
    "activo": True, "textura_suelo": "Arenoso", "capacidad_campo": 0.14, "punto_marchitez": 0.04,
    "agotamiento_maximo": 0.25, "infiltracion_basica_mmh": 40.0, "ancho_humedo_m": 2.0,
    "profundidad_raices_m": 0.5, "diametro_bulbo_m": None, "distancia_hileras_m": 6.0,
    "distancia_plantas_m": 2.0, "mangueras_por_hilera": 4, "separacion_mangueras_m": 0.5,
    "distancia_goteros_m": 0.5, "caudal_gotero_lh": 1.6, "reposo_min_por_hora": 5.0,
    "eficiencia_aplicacion": 0.85, "fase_fenologica": "Crecimiento de fruta",
    "agotamiento_por_fase": {"Vegetativo": 0.10, "Floración": 0.05, "Cuajado": 0.05,
                             "Crecimiento de fruta": 0.05, "Maduración": 0.10, "Cosecha": 0.10},
    "agotamiento_automatico": True, "umbral_etr_1": 2.5, "umbral_etr_2": 5.0,
    "modo_ventana": "automatico_con_respaldo",
    "curvas": {
        "1": {"6": 2, "7": 3, "8": 5, "9": 9, "10": 13, "11": 13, "12": 13, "13": 13, "14": 12, "15": 9,
              "16": 5, "17": 3},
        "2": {"6": 6, "7": 8, "8": 9, "9": 9, "10": 9, "11": 9, "12": 9, "13": 9, "14": 9, "15": 9,
              "16": 8, "17": 6},
        "3": {"3": 4, "4": 5, "5": 5, **{str(h): 6 for h in range(6, 18)}, "18": 5, "19": 5, "20": 4},
    },
    "ajustar_pulso_al_total": True,
}


# --- Conversión y validación ------------------------------------------------------------

def _curvas(crudas: dict[str, dict[str, float]]) -> dict[str, dict[int, float]]:
    salida = {}
    for nombre, curva in crudas.items():
        salida[nombre] = {int(h): float(p) for h, p in curva.items()}
    return salida


def a_parametros(valores: dict[str, Any] | ParametrosPulsos) -> calculo_pulsos.Parametros:
    """Fila o diccionario → ``calculo_pulsos.Parametros``."""
    v = {c: getattr(valores, c) for c in CAMPOS} if isinstance(valores, ParametrosPulsos) else valores
    return calculo_pulsos.Parametros(
        capacidad_campo=v["capacidad_campo"], punto_marchitez=v["punto_marchitez"],
        agotamiento_maximo=v["agotamiento_maximo"], infiltracion_basica_mmh=v["infiltracion_basica_mmh"],
        ancho_humedo_m=v["ancho_humedo_m"], profundidad_raices_m=v["profundidad_raices_m"],
        diametro_bulbo_m=v["diametro_bulbo_m"], distancia_hileras_m=v["distancia_hileras_m"],
        distancia_plantas_m=v["distancia_plantas_m"], mangueras_por_hilera=int(v["mangueras_por_hilera"]),
        separacion_mangueras_m=v["separacion_mangueras_m"], distancia_goteros_m=v["distancia_goteros_m"],
        caudal_gotero_lh=v["caudal_gotero_lh"], reposo_min_por_hora=v["reposo_min_por_hora"],
        eficiencia_aplicacion=v["eficiencia_aplicacion"], fase_fenologica=v["fase_fenologica"],
        agotamiento_por_fase={k: float(x) for k, x in v["agotamiento_por_fase"].items()},
        agotamiento_automatico=v["agotamiento_automatico"], umbral_etr_1=v["umbral_etr_1"],
        umbral_etr_2=v["umbral_etr_2"], modo_ventana=v["modo_ventana"], curvas=_curvas(v["curvas"]),
        ajustar_pulso_al_total=v["ajustar_pulso_al_total"],
    )


def validar(datos: ParametrosPulsosEntrada) -> None:
    """Reglas que cruzan campos (los rangos de cada campo los valida el esquema)."""
    errores = []
    numeros = [v for v in datos.model_dump().values() if isinstance(v, float)]
    if not all(math.isfinite(v) for v in numeros):
        errores.append("Todos los valores deben ser números finitos")
    if datos.punto_marchitez >= datos.capacidad_campo:
        errores.append("El punto de marchitez debe ser menor que la capacidad de campo")
    if datos.umbral_etr_1 >= datos.umbral_etr_2:
        errores.append("El umbral 1 de ETr debe ser menor que el umbral 2")
    if datos.fase_fenologica not in datos.agotamiento_por_fase:
        errores.append("La fase fenológica elegida no está en la tabla de agotamiento por fase")
    for fase, valor in datos.agotamiento_por_fase.items():
        if not 0 < len(fase.strip()) <= 40:
            errores.append("Los nombres de fase deben tener entre 1 y 40 caracteres")
        if not (math.isfinite(valor) and 0 < valor <= datos.agotamiento_maximo):
            errores.append(f"El agotamiento de «{fase}» debe ser mayor que 0 y como máximo el agotamiento máximo")
    if set(datos.curvas) != set(calculo_pulsos.CURVAS):
        errores.append("Debe haber exactamente las curvas 1, 2 y 3")
    for nombre in sorted(set(datos.curvas) & set(calculo_pulsos.CURVAS)):
        curva = datos.curvas[nombre]
        try:
            horas = {int(h): p for h, p in curva.items()}
        except ValueError:
            errores.append(f"Curva {nombre}: las horas deben ser números enteros")
            continue
        if any(h not in calculo_pulsos.HORAS_VENTANA for h in horas):
            errores.append(f"Curva {nombre}: solo se admiten horas de 03:00 a 20:00 (inicio de cada hora)")
        if any(not (math.isfinite(p) and 0 <= p <= 100) for p in horas.values()):
            errores.append(f"Curva {nombre}: cada % debe estar entre 0 y 100")
        elif abs(sum(horas.values()) - 100) > 0.01:
            errores.append(f"Curva {nombre}: suma {sum(horas.values()):g} % y debe sumar 100 %")
    if errores:
        raise DatosInvalidos(". ".join(dict.fromkeys(errores)))


# --- Lectura y edición --------------------------------------------------------------------

def _n_turnos(db: Session, modulo_id: int) -> int:
    return sum(1 for t in repo_riego.turnos_de_modulo(db, modulo_id) if t.activo) or 1


def _salida(db: Session, modulo_id: int, valores: dict[str, Any], fila: ParametrosPulsos | None) -> dict[str, Any]:
    salida: dict[str, Any] = {**valores, "modulo_id": modulo_id, "guardado": fila is not None,
                              "derivados": None, "avisos": []}
    if fila is not None:
        salida["actualizado_at"] = fila.updated_at
        salida["actualizado_por"] = repo_riego.usernames(db, [fila.actualizado_por]).get(fila.actualizado_por)
    n = _n_turnos(db, modulo_id)
    try:
        p = a_parametros(valores)
        d = calculo_pulsos.derivados(p, n)
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        salida["avisos"].append(f"No se pudieron calcular los derivados: {exc}")
        return salida
    salida["derivados"] = {"turnos": n, **{k: getattr(d, k) for k in d.__dataclass_fields__}}
    if d.intensidad_mmh > p.infiltracion_basica_mmh:
        salida["avisos"].append("La intensidad del gotero supera la infiltración básica del suelo")
    if d.ancho_bulbos_m < p.ancho_humedo_m - 0.005:
        salida["avisos"].append(f"Los bulbos mojan {d.ancho_bulbos_m:.2f} m, menos que el ancho efectivo indicado")
    if p.agotamiento_automatico and d.agotamiento_max_bloque < d.agotamiento_fase:
        salida["avisos"].append(
            f"El agotamiento de la fase ({d.agotamiento_fase:.0%}) no cabe en un bloque de 3 h con "
            f"{n} turnos: se usa {d.agotamiento_max_bloque:.1%}")
    return salida


def obtener(db: Session, modulo_id: int) -> dict[str, Any]:
    datos_service.modulo_o_404(db, modulo_id)
    fila = repo.parametros(db, modulo_id)
    valores = {c: getattr(fila, c) for c in CAMPOS} if fila else dict(POR_DEFECTO)
    return _salida(db, modulo_id, valores, fila)


def activos(db: Session, modulo_id: int) -> calculo_pulsos.Parametros | None:
    """Parámetros para generar, o ``None`` si el módulo no usa riego por pulsos."""
    fila = repo.parametros(db, modulo_id)
    return a_parametros(fila) if fila is not None and fila.activo else None


def actualizar(db: Session, modulo_id: int, datos: ParametrosPulsosEntrada, actor: Usuario,
               contexto: ContextoPeticion | None = None) -> dict[str, Any]:
    datos_service.modulo_o_404(db, modulo_id)
    validar(datos)
    valores = datos.model_dump()
    valores["curvas"] = {c: {str(int(h)): p for h, p in curva.items()} for c, curva in datos.curvas.items()}
    valores["agotamiento_por_fase"] = {f.strip(): x for f, x in datos.agotamiento_por_fase.items()}
    valores["textura_suelo"] = datos.textura_suelo.strip()
    valores["fase_fenologica"] = datos.fase_fenologica.strip()
    try:
        calculo_pulsos.derivados(a_parametros(valores), _n_turnos(db, modulo_id))
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise DatosInvalidos(f"Con estos valores no se puede calcular el pulso: {exc}") from None
    fila = repo.parametros(db, modulo_id, bloquear=True)
    antes = {c: getattr(fila, c) for c in CAMPOS} if fila else None
    if fila is None:
        fila = ParametrosPulsos(modulo_id=modulo_id)
        db.add(fila)
    for campo, valor in valores.items():
        setattr(fila, campo, valor)
    fila.actualizado_por = actor.id
    db.flush()
    db.refresh(fila)
    cambios = {c: {"antes": antes[c] if antes else None, "despues": valores[c]}
               for c in CAMPOS if antes is None or antes[c] != valores[c]}
    auditoria_service.registrar(db, accion="actualizar_parametros_pulsos", entidad="modulo", entidad_id=modulo_id,
                                actor=actor, detalle={"cambios": cambios}, contexto=contexto)
    return _salida(db, modulo_id, {c: getattr(fila, c) for c in CAMPOS}, fila)
