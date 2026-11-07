"""Reporte de una corrida de entrenamiento: Excel estructurado + gráficos + CSV.

Estructura de la carpeta ``reports/entrenamientos/<AAAA-MM-DD_HHMM>/``::

    metricas_modelos.xlsx   Reporte principal (ver hojas abajo)
    graficos/               PNG numerados (también incrustados en el Excel)
    datos/                  CSV con comparación, predicciones de test y métricas

Hojas del Excel:

1. Resumen          datos de la corrida y modelo elegido por target vs persistencia
2. Comp_n_ciclos    todos los modelos para el número de ciclos (validación y test)
3. Comp_m3ha        todos los modelos para m3/ha por ciclo
4. Comp_inicio      todos los modelos para la hora de inicio
5. Plan_completo    error del plan armado (n predicho -> ciclos -> horario) y derivados
6. Por_turno        errores en test por turno
7. Por_mes          errores en test por mes
   Rangos           cobertura real del intervalo p10–p90 en test
   Historial        todas las corridas, para ver el efecto de datos/features/modelos
8. Confusion        matriz de confusión del número de ciclos
9. Importancias     variables más importantes de los modelos de árboles
10. Graficos        todos los gráficos
11. Pred_turno_test / Pred_ciclo_test / Plan_test  datos observados vs predichos
12. Features        variables usadas y excluidas
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from riego_ml.modeling import graficos
from riego_ml.modeling.graficos import NOMBRES
from riego_ml.utils.tiempo import minutes_to_hhmm

AZUL_OSCURO = "1F4E78"
FILL_HEADER = PatternFill("solid", start_color=AZUL_OSCURO)
FILL_ELEGIDO = PatternFill("solid", start_color="DCEBFB")
FILL_MEJOR = PatternFill("solid", start_color="D7F0E3")
FILL_REF = PatternFill("solid", start_color="F2F2F0")
BORDE = Border(bottom=Side(style="thin", color="D9D9D6"))
FUENTE = "Arial"

METRICAS_CLASIF = [
    ("accuracy", "Acierto", "0.0%", True),
    ("accuracy_pm1", "Acierto ±1 ciclo", "0.0%", True),
    ("f1_macro", "F1 macro", "0.000", True),
    ("balanced_accuracy", "Acierto balanceado", "0.000", True),
    ("cohen_kappa", "Kappa", "0.000", True),
    ("mae_ciclos", "MAE (ciclos)", "0.000", False),
]
METRICAS_REG = [
    ("rmse", "RMSE", "0.00", False),
    ("mae", "MAE", "0.00", False),
    ("r2", "R²", "0.000", True),
    ("mbe", "Sesgo (MBE)", "0.00", None),
    ("kge", "KGE", "0.000", True),
    ("willmott_d", "Willmott d", "0.000", True),
    ("pbias_pct", "PBIAS %", "0.0", None),
]


@dataclass
class ResultadosEntrenamiento:
    comparacion: pd.DataFrame
    elegidos: dict[str, dict[str, Any]]
    descripcion_targets: dict[str, str]
    importancias: dict[str, dict[str, dict[str, float]]]
    pred_turno_test: pd.DataFrame
    pred_ciclo_test: pd.DataFrame
    plan_test: pd.DataFrame
    plan_test_largo: pd.DataFrame
    ciclos_reales: pd.DataFrame
    etiquetas: list[int]
    info_corrida: dict[str, Any] = field(default_factory=dict)
    features: dict[str, list[str]] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Tablas
# --------------------------------------------------------------------------- #
def _fmt_min(minutos: float) -> str:
    minutos = abs(float(minutos))
    h, m = divmod(int(round(minutos)), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _valor(comp: pd.DataFrame, target: str, modelo: str, conjunto: str, metrica: str) -> float:
    fila = comp[(comp["target"] == target) & (comp["modelo"] == modelo) & (comp["conjunto"] == conjunto)]
    return float(fila[metrica].iloc[0]) if len(fila) and metrica in fila else np.nan


def tabla_resumen(r: ResultadosEntrenamiento) -> pd.DataFrame:
    comp = r.comparacion
    filas = []
    for target, info in r.elegidos.items():
        clasif = info["tarea"] == "clasificacion"
        criterio = "f1_macro" if clasif else "rmse"
        val, test = info["validacion"][criterio], info["test"][criterio]
        pers = _valor(comp, target, "persistencia", "test", criterio)
        if info["familia"] == "persistencia":
            mejora = "es la referencia"
        else:
            delta = (test - pers) / pers if clasif else (pers - test) / pers
            mejora = f"{delta:+.1%}"
        t = info["test"]
        if clasif:
            lectura = f"acierta {t['accuracy']:.0%} de los días ({t['accuracy_pm1']:.0%} con ±1 ciclo)"
        elif target == "inicio_min":
            lectura = f"error típico ±{_fmt_min(t['mae'])} (MAE) · R² {t['r2']:.2f}"
        else:
            lectura = f"error típico ±{t['mae']:.1f} m3/ha (MAE) · R² {t['r2']:.2f}"
        filas.append({
            "Target": target,
            "Qué predice": r.descripcion_targets.get(target, target),
            "Modelo elegido": NOMBRES.get(info["familia"], info["familia"]),
            "Criterio de elección": "F1 macro (mayor es mejor)" if clasif else "RMSE (menor es mejor)",
            "Validación": val,
            "Test": test,
            "Persistencia en test": pers,
            "Mejora vs persistencia": mejora,
            "Lectura del resultado (test)": lectura,
        })
    dur = comp[(comp["target"] == "duracion_min") & ~comp["modelo"].str.contains("real")]
    if len(dur):
        d = dur.iloc[0]
        filas.append({
            "Target": "duracion_min", "Qué predice": "Duración de cada ciclo (derivada del volumen)",
            "Modelo elegido": f"{NOMBRES.get(r.elegidos['riego_m3ha']['familia'])} + caudal del turno",
            "Criterio de elección": "derivada (no se entrena)", "Validación": np.nan, "Test": d["rmse"],
            "Persistencia en test": np.nan, "Mejora vs persistencia": "—",
            "Lectura del resultado (test)": f"error típico ±{_fmt_min(d['mae'])} (MAE) · R² {d['r2']:.2f}",
        })
    return pd.DataFrame(filas)


def tabla_comparacion(comp: pd.DataFrame, target: str, clasificacion: bool, elegido: str) -> pd.DataFrame:
    metricas = METRICAS_CLASIF if clasificacion else METRICAS_REG
    d = comp[(comp["target"] == target) & comp["conjunto"].isin(["validacion", "test"])]
    filas = []
    for modelo in [m for m in NOMBRES if m in set(d["modelo"])]:
        fila = {"Modelo": NOMBRES[modelo], "Elegido": "★" if modelo == elegido else ""}
        for conjunto, etiqueta in (("validacion", "Val"), ("test", "Test")):
            x = d[(d["modelo"] == modelo) & (d["conjunto"] == conjunto)].iloc[0]
            for clave, nombre, _, _ in metricas:
                fila[f"{etiqueta} · {nombre}"] = x.get(clave, np.nan)
        x = d[(d["modelo"] == modelo) & (d["conjunto"] == "test")].iloc[0]
        fila["n test"] = int(x["n"])
        fila["Seg. entrenamiento"] = x.get("segundos", np.nan)
        filas.append(fila)
    return pd.DataFrame(filas)


def tabla_rangos(comp: pd.DataFrame) -> pd.DataFrame:
    d = comp[comp["target"].astype(str).str.startswith("rango ")].copy()
    if d.empty:
        return pd.DataFrame()
    nombres = {"rango riego_m3ha": "m3/ha por ciclo", "rango inicio_min": "Hora de inicio (min)"}
    return pd.DataFrame({
        "Qué": d["target"].map(nombres),
        "Modelo": d["modelo"],
        "Cobertura real en test": d["cobertura"],
        "Cobertura esperada": d["cobertura_esperada"],
        "Ancho medio del rango": d["ancho_medio"],
        "Ciclos": d["n"],
    })


def tabla_historial(carpeta_entrenamientos: Path) -> pd.DataFrame:
    """Una fila por corrida (se reconstruye leyendo cada carpeta)."""
    filas = []
    for carpeta in sorted(p for p in carpeta_entrenamientos.iterdir() if p.is_dir()):
        resumen_json, comp_csv = carpeta / "datos" / "resumen.json", carpeta / "datos" / "comparacion_modelos.csv"
        if not (resumen_json.exists() and comp_csv.exists()):
            continue
        info = json.loads(resumen_json.read_text(encoding="utf-8"))
        corrida = info.get("corrida", {})
        comp = pd.read_csv(comp_csv)
        elegidos = {r["Target"]: r["Modelo elegido"] for r in info.get("resumen", [])}
        test = comp[comp["conjunto"] == "test"]

        def metrica(target, metrica, modelo=None):
            d = test[test["target"] == target]
            if modelo is not None:
                d = d[d["modelo"] == modelo]
            return float(d[metrica].iloc[0]) if len(d) and metrica in d else np.nan

        def del_elegido(target, met):
            nombre = elegidos.get(target)
            alias = {"Persistencia (ayer)": "persistencia"}  # nombre usado en corridas anteriores
            clave = alias.get(nombre) or next((k for k, v in NOMBRES.items() if v == nombre), nombre)
            return metrica(target, met, clave)

        filas.append({
            "Corrida": carpeta.name,
            "Datos usados": corrida.get("Datos usados", ""),
            "Test": corrida.get("Test", ""),
            "Features": corrida.get("Features", "base (sin registro)"),
            "N° ciclos: modelo": elegidos.get("n_ciclos", ""),
            "N° ciclos: acierto": del_elegido("n_ciclos", "accuracy"),
            "N° ciclos: F1": del_elegido("n_ciclos", "f1_macro"),
            "m3/ha: modelo": elegidos.get("riego_m3ha", ""),
            "m3/ha: RMSE": del_elegido("riego_m3ha", "rmse"),
            "m3/ha: MAE": del_elegido("riego_m3ha", "mae"),
            "Inicio: modelo": elegidos.get("inicio_min", ""),
            "Inicio: RMSE (min)": del_elegido("inicio_min", "rmse"),
            "Inicio: MAE (min)": del_elegido("inicio_min", "mae"),
            "Duración: MAE (min)": metrica("duracion_min", "mae", None),
            "Plan: RMSE total m3/ha": metrica("plan: riego_total_m3ha", "rmse"),
            "Plan: MAE inicio 1er ciclo (min)": metrica("plan: inicio_primer_min", "mae"),
        })
    return pd.DataFrame(filas)


def tabla_plan(comp: pd.DataFrame) -> pd.DataFrame:
    nombres = {
        "plan: riego_total_m3ha": "Riego total del turno-día (m3/ha)",
        "plan: duracion_total_min": "Duración total del turno-día (min)",
        "plan: inicio_primer_min": "Inicio del primer ciclo (min)",
        "plan: fin_ultimo_min": "Fin del último ciclo (min)",
        "duracion_min": "Duración por ciclo (min)",
        "fin_min": "Hora de fin por ciclo (min)",
    }
    d = comp[comp["target"].isin(nombres)].copy()
    d.insert(0, "Qué se evalúa", d["target"].map(nombres))
    d["Condición"] = np.where(d["target"].str.startswith("plan:"), "n_ciclos predicho (plan real de uso)",
                              "n_ciclos real (solo error de los regresores)")
    columnas = ["Qué se evalúa", "modelo", "Condición", "n", "rmse", "mae", "r2", "mbe", "kge"]
    return d[columnas].rename(columns={"modelo": "Modelo", "rmse": "RMSE", "mae": "MAE", "r2": "R²",
                                       "mbe": "Sesgo (MBE)", "kge": "KGE"})


def _errores_por(r: ResultadosEntrenamiento, clave_turno, clave_ciclo) -> pd.DataFrame:
    t, c = r.pred_turno_test, r.pred_ciclo_test
    acierto = (t["n_ciclos_real"] == t["n_ciclos_pred"]).groupby(clave_turno(t)).mean()
    e_m3 = c["riego_m3ha_pred"] - c["riego_m3ha_real"]
    e_ini = c["inicio_min_pred"] - c["inicio_min_real"]
    e_dur = c["duracion_min_pred"] - c["duracion_min_real"]
    g = clave_ciclo(c)
    tabla = pd.DataFrame({
        "Acierto n_ciclos": acierto,
        "RMSE m3/ha": np.sqrt((e_m3**2).groupby(g).mean()),
        "MAE m3/ha": e_m3.abs().groupby(g).mean(),
        "Sesgo m3/ha": e_m3.groupby(g).mean(),
        "MAE inicio (min)": e_ini.abs().groupby(g).mean(),
        "MAE duración (min)": e_dur.abs().groupby(g).mean(),
        "Turno-días": t.groupby(clave_turno(t)).size(),
        "Ciclos": c.groupby(g).size(),
    })
    return tabla


def tabla_por_turno(r: ResultadosEntrenamiento) -> pd.DataFrame:
    return _errores_por(r, lambda d: d["Turno"], lambda d: d["Turno"]).rename_axis("Turno")


def tabla_por_mes(r: ResultadosEntrenamiento) -> pd.DataFrame:
    def mes(d):
        return d["Fecha"].dt.to_period("M").astype(str)
    return _errores_por(r, mes, mes).rename_axis("Mes")


def tabla_confusion(r: ResultadosEntrenamiento) -> pd.DataFrame:
    t = r.pred_turno_test
    cm = pd.crosstab(t["n_ciclos_real"], t["n_ciclos_pred"]).reindex(
        index=r.etiquetas, columns=r.etiquetas, fill_value=0
    )
    cm.index = [f"Real {e}" for e in cm.index]
    cm.columns = [f"Pred {e}" for e in cm.columns]
    cm["Total real"] = cm.sum(axis=1)
    cm["Acierto de la clase"] = [
        cm.iloc[i, i] / cm["Total real"].iloc[i] if cm["Total real"].iloc[i] else np.nan
        for i in range(len(r.etiquetas))
    ]
    return cm.rename_axis("n_ciclos").reset_index()


def tabla_importancias(r: ResultadosEntrenamiento, top: int = 20) -> pd.DataFrame:
    filas = []
    for target, por_modelo in r.importancias.items():
        for modelo, imp in por_modelo.items():
            for rank, (feature, valor) in enumerate(list(imp.items())[:top], start=1):
                filas.append({"Target": target, "Modelo": NOMBRES.get(modelo, modelo),
                              "Ranking": rank, "Variable": feature, "Importancia": valor})
    return pd.DataFrame(filas)


def _redondear(df: pd.DataFrame, decimales: int = 2) -> pd.DataFrame:
    numericas = df.select_dtypes("number").columns
    return df.assign(**{c: df[c].round(decimales) for c in numericas})


def _con_horas(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega la versión HH:MM de cada columna de minutos de inicio/fin."""
    out = df.copy()
    for col in list(out.columns):
        if col.endswith(("_real", "_pred")) and ("inicio" in col or "fin" in col) and "_min" in col:
            out[col.replace("_min", "_hora")] = out[col].map(minutes_to_hhmm)
    return out


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
def _formato_columna(nombre: str) -> str | None:
    n = nombre.lower()
    if "acierto" in n or "%" == n[-1:]:
        return "0.0%"
    if "fecha" in n:
        return "yyyy-mm-dd"
    if n.startswith(("n ", "turno-días", "ciclos")) or n in {"n", "ranking", "total real"}:
        return "0"
    return None


def _escribir_tabla(ws, df: pd.DataFrame, fila: int, formatos: dict[str, str] | None = None,
                    resaltar: pd.Series | None = None, mejores: dict[str, bool] | None = None,
                    max_ancho: int = 42) -> int:
    """Escribe ``df`` desde ``fila`` con estilo. Devuelve la fila siguiente libre."""
    formatos = formatos or {}
    for j, col in enumerate(df.columns, start=1):
        celda = ws.cell(row=fila, column=j, value=str(col))
        celda.font = Font(name=FUENTE, bold=True, color="FFFFFF", size=10)
        celda.fill = FILL_HEADER
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[fila].height = 32
    mejores_idx = {}
    for col, mayor in (mejores or {}).items():
        if col in df and df[col].notna().any():
            serie = pd.to_numeric(df[col], errors="coerce")
            mejores_idx[col] = serie.idxmax() if mayor else serie.idxmin()
    for i, (idx, registro) in enumerate(df.iterrows(), start=1):
        for j, col in enumerate(df.columns, start=1):
            valor = registro[col]
            if isinstance(valor, (np.floating, float)) and not np.isfinite(valor):
                valor = None
            elif isinstance(valor, np.integer):
                valor = int(valor)
            elif isinstance(valor, np.floating):
                valor = float(valor)
            elif isinstance(valor, pd.Timestamp):
                valor = valor.to_pydatetime()
            celda = ws.cell(row=fila + i, column=j, value=valor)
            celda.font = Font(name=FUENTE, size=10)
            celda.border = BORDE
            fmt = formatos.get(col) or _formato_columna(str(col))
            if fmt is None and isinstance(valor, float):
                fmt = "0.00"
            if fmt:
                celda.number_format = fmt
            if resaltar is not None and bool(resaltar.loc[idx]):
                celda.fill = FILL_ELEGIDO
                celda.font = Font(name=FUENTE, size=10, bold=True)
            if mejores_idx.get(col) == idx:
                celda.fill = FILL_MEJOR
                celda.font = Font(name=FUENTE, size=10, bold=True, color="0B5D33")
    for j, col in enumerate(df.columns, start=1):
        muestra = df[col].head(200).map(lambda v: len(str(v))).max() if len(df) else 0
        ancho = max(len(str(col)) * 0.9, (muestra or 0) + 2, 10)
        letra = get_column_letter(j)
        ws.column_dimensions[letra].width = max(ws.column_dimensions[letra].width or 0, min(ancho, max_ancho))
    return fila + len(df) + 2


def _titulo(ws, titulo: str, nota: str | None = None) -> int:
    ws["A1"] = titulo
    ws["A1"].font = Font(name=FUENTE, bold=True, size=14, color=AZUL_OSCURO)
    if nota:
        ws["A2"] = nota
        ws["A2"].font = Font(name=FUENTE, italic=True, size=10, color="52514E")
    ws.sheet_view.showGridLines = False
    return 4


def _hoja_tabla(wb, nombre, titulo, nota, df, congelar=True, **kwargs):
    ws = wb.create_sheet(nombre)
    fila = _titulo(ws, titulo, nota)
    _escribir_tabla(ws, df, fila, **kwargs)
    if congelar:
        ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    return ws


def escribir_excel(r: ResultadosEntrenamiento, tablas: dict[str, pd.DataFrame], imagenes: list[tuple[str, Path]],
                   ruta: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    fila = _titulo(ws, "Reporte de entrenamiento – Plan de riego",
                   "El modelo de cada target se elige en VALIDACIÓN; el TEST (período más reciente) solo se reporta.")
    info = pd.DataFrame(list(r.info_corrida.items()), columns=["Dato", "Valor"])
    fila = _escribir_tabla(ws, info, fila, max_ancho=70)
    ws.cell(row=fila, column=1, value="Modelo elegido por target").font = Font(name=FUENTE, bold=True, size=12,
                                                                                 color=AZUL_OSCURO)
    resumen = tablas["resumen"]
    fmt = {"Validación": "0.000", "Test": "0.000", "Persistencia en test": "0.000"}
    fila = _escribir_tabla(ws, resumen, fila + 1, formatos=fmt, max_ancho=60)
    notas = [
        "Cómo leer:",
        "• Persistencia = repetir lo que hizo el mismo turno/ciclo el día anterior. Es la referencia mínima a superar.",
        "• RMSE y MAE están en las unidades del target (m3/ha o minutos). R² = 1 es perfecto; 0 = predecir la media.",
        "• La duración no se entrena: se calcula con el m3/ha predicho y el caudal histórico de cada turno.",
        "• Celdas verdes = mejor valor de la columna; filas azules = modelo elegido.",
    ]
    for k, texto in enumerate(notas):
        c = ws.cell(row=fila + k, column=1, value=texto)
        c.font = Font(name=FUENTE, size=10, bold=k == 0, color="52514E")
    ws.column_dimensions["A"].width = 34

    for target, hoja in (("n_ciclos", "Comp_n_ciclos"), ("riego_m3ha", "Comp_m3ha"), ("inicio_min", "Comp_inicio")):
        df = tablas[f"comp_{target}"]
        clasif = target == "n_ciclos"
        metricas = METRICAS_CLASIF if clasif else METRICAS_REG
        formatos = {f"{e} · {n}": f for _, n, f, _ in metricas for e in ("Val", "Test")}
        mejores = {f"{e} · {n}": m for _, n, _, m in metricas for e in ("Val", "Test") if m is not None}
        unidad = "" if clasif else (" Unidades: m3/ha." if target == "riego_m3ha" else " Unidades: minutos.")
        _hoja_tabla(wb, hoja, f"Comparación de modelos – {r.descripcion_targets[target]}",
                    "Fila azul = elegido (mejor en validación). Verde = mejor valor de cada columna." + unidad,
                    df, formatos=formatos, resaltar=df["Elegido"] == "★", mejores=mejores)

    _hoja_tabla(wb, "Plan_completo", "Error del plan completo en test",
                "Plan real de uso: n_ciclos predicho -> m3/ha e inicio por ciclo -> duración por caudal -> horario.",
                tablas["plan"], formatos={"RMSE": "0.00", "MAE": "0.00", "R²": "0.000", "Sesgo (MBE)": "0.00",
                                          "KGE": "0.000"})
    _hoja_tabla(wb, "Por_turno", "Errores en test por turno", "Modelos elegidos. Sesgo > 0 = el modelo sobreestima.",
                tablas["por_turno"].reset_index())
    _hoja_tabla(wb, "Por_mes", "Errores en test por mes", "Modelos elegidos.", tablas["por_mes"].reset_index())
    if not tablas["rangos"].empty:
        _hoja_tabla(wb, "Rangos", "Rangos p10–p90: ¿cuántas veces el valor real cayó dentro?",
                    "Si la cobertura real se parece a la esperada, el rango es confiable.", tablas["rangos"],
                    formatos={"Cobertura real en test": "0.0%", "Cobertura esperada": "0.0%",
                              "Ancho medio del rango": "0.0"})
    if not tablas["historial"].empty:
        _hoja_tabla(wb, "Historial", "Historial de entrenamientos",
                    "Una fila por corrida: sirve para ver cómo influyen los datos nuevos, las features y los modelos.",
                    tablas["historial"],
                    formatos={"N° ciclos: acierto": "0.0%", "N° ciclos: F1": "0.000"}, max_ancho=30)
    _hoja_tabla(wb, "Confusion", "Matriz de confusión – número de ciclos (test)",
                "Filas = real, columnas = predicho. La diagonal son los aciertos.", tablas["confusion"],
                formatos={"Acierto de la clase": "0.0%"})
    _hoja_tabla(wb, "Importancias", "Variables más importantes (modelos de árboles)",
                "Importancia relativa de cada variable dentro de cada modelo (suma 1).", tablas["importancias"],
                formatos={"Importancia": "0.0000"})

    wsg = wb.create_sheet("Graficos")
    fila = _titulo(wsg, "Gráficos", "También están como PNG en la carpeta graficos/.")
    for titulo, ruta_png in imagenes:
        wsg.cell(row=fila, column=1, value=titulo).font = Font(name=FUENTE, bold=True, size=11, color=AZUL_OSCURO)
        img = Image(str(ruta_png))
        escala = min(1.0, 900 / img.width)
        img.width, img.height = img.width * escala, img.height * escala
        wsg.add_image(img, f"A{fila + 1}")
        fila += int(img.height / 20) + 4

    _hoja_tabla(wb, "Pred_turno_test", "Número de ciclos en test: real vs cada modelo", None,
                tablas["pred_turno"], max_ancho=18)
    _hoja_tabla(wb, "Pred_ciclo_test", "Ciclos en test: real vs predicho (n_ciclos real)", None,
                tablas["pred_ciclo"], max_ancho=18)
    _hoja_tabla(wb, "Plan_test", "Plan completo en test por turno-día: real vs predicho", None,
                tablas["plan_test"], max_ancho=18)
    feats = pd.DataFrame({
        "Variable": [*r.features.get("turno", []), *[c for c in r.features.get("ciclo", [])
                                                     if c not in r.features.get("turno", [])],
                     *r.features.get("excluidas", [])],
    })
    feats["Uso"] = (["turno-día y ciclo"] * len(r.features.get("turno", []))
                    + ["solo modelos por ciclo"] * (len(feats) - len(r.features.get("turno", []))
                                                    - len(r.features.get("excluidas", [])))
                    + ["excluida (solo revisión)"] * len(r.features.get("excluidas", [])))
    _hoja_tabla(wb, "Features", "Variables de entrada", "Todas conocidas a las 00:00 del día a planificar.", feats)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)


# --------------------------------------------------------------------------- #
def generar_graficos(r: ResultadosEntrenamiento, carpeta: Path) -> list[tuple[str, Path]]:
    carpeta.mkdir(parents=True, exist_ok=True)
    comp, el = r.comparacion, r.elegidos
    out: list[tuple[str, Path]] = []

    def add(titulo, ruta):
        out.append((titulo, ruta))

    add("Comparación – número de ciclos", graficos.comparacion_modelos(
        comp, "n_ciclos", "f1_macro", "Número de ciclos: F1 macro por modelo", el["n_ciclos"]["familia"], True,
        carpeta, "01_comparacion_n_ciclos"))
    add("Comparación – acierto número de ciclos", graficos.comparacion_modelos(
        comp, "n_ciclos", "accuracy", "Número de ciclos: acierto por modelo", el["n_ciclos"]["familia"], True,
        carpeta, "02_comparacion_n_ciclos_acierto"))
    add("Comparación – m3/ha por ciclo", graficos.comparacion_modelos(
        comp, "riego_m3ha", "rmse", "m3/ha por ciclo: RMSE por modelo", el["riego_m3ha"]["familia"], False,
        carpeta, "03_comparacion_m3ha"))
    add("Comparación – hora de inicio", graficos.comparacion_modelos(
        comp, "inicio_min", "rmse", "Hora de inicio: RMSE (min) por modelo", el["inicio_min"]["familia"], False,
        carpeta, "04_comparacion_inicio"))
    t, c = r.pred_turno_test, r.pred_ciclo_test
    add("Matriz de confusión", graficos.matriz_confusion(
        t["n_ciclos_real"], t["n_ciclos_pred"], r.etiquetas, el["n_ciclos"]["familia"], carpeta,
        "05_confusion_n_ciclos"))
    add("m3/ha real vs predicho", graficos.real_vs_predicho(
        c["riego_m3ha_real"], c["riego_m3ha_pred"], "m3/ha por ciclo: real vs predicho", "m3/ha",
        el["riego_m3ha"]["familia"], carpeta, "06_real_vs_pred_m3ha"))
    add("Hora de inicio real vs predicha", graficos.real_vs_predicho(
        c["inicio_min_real"], c["inicio_min_pred"], "Hora de inicio: real vs predicha", "h",
        el["inicio_min"]["familia"], carpeta, "07_real_vs_pred_inicio", escala=60))
    add("Duración real vs predicha", graficos.real_vs_predicho(
        c["duracion_min_real"], c["duracion_min_pred"], "Duración por ciclo: real vs predicha", "min",
        el["riego_m3ha"]["familia"], carpeta, "08_real_vs_pred_duracion"))
    add("Distribución de errores", graficos.residuos({
        "Error m3/ha por ciclo": ((c["riego_m3ha_pred"] - c["riego_m3ha_real"]).to_numpy(), "m3/ha"),
        "Error hora de inicio": ((c["inicio_min_pred"] - c["inicio_min_real"]).to_numpy(), "min"),
        "Error duración": ((c["duracion_min_pred"] - c["duracion_min_real"]).to_numpy(), "min"),
    }, carpeta, "09_distribucion_errores"))
    add("Serie temporal del plan", graficos.serie_plan(r.plan_test, carpeta, "10_serie_riego_total_test"))
    por_turno, por_mes = tabla_por_turno(r), tabla_por_mes(r)
    columnas = {"Acierto n_ciclos": "Acierto n_ciclos", "MAE m3/ha": "MAE m3/ha", "MAE inicio (min)": "MAE inicio (min)"}
    add("Errores por turno", graficos.error_por_grupo(por_turno, columnas, "Errores en test por turno",
                                                      carpeta, "11_errores_por_turno"))
    add("Errores por mes", graficos.error_por_grupo(por_mes, columnas, "Errores en test por mes",
                                                    carpeta, "12_errores_por_mes", linea=True))
    n = 13
    for target, por_modelo in r.importancias.items():
        familia = el[target]["familia"] if el[target]["familia"] in por_modelo else (
            "random_forest" if "random_forest" in por_modelo else next(iter(por_modelo), None))
        if familia:
            add(f"Importancias – {target}", graficos.importancias(
                por_modelo[familia], f"Variables más importantes: {target}", familia, carpeta,
                f"{n:02d}_importancias_{target}"))
            n += 1
    dias = r.plan_test.assign(err=(r.plan_test["riego_total_m3ha_pred"] - r.plan_test["riego_total_m3ha_real"]).abs())
    dia_tipico = dias.groupby("Fecha")["err"].mean().sort_values()
    if len(dia_tipico):
        fecha = dia_tipico.index[len(dia_tipico) // 2]
        add("Horario de un día típico de test", graficos.gantt_dia(
            r.plan_test_largo, r.ciclos_reales, fecha, carpeta, f"{n:02d}_horario_dia_tipico"))
    return out


def generar_reporte(r: ResultadosEntrenamiento, carpeta: Path, logger=None) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    datos = carpeta / "datos"
    datos.mkdir(exist_ok=True)
    tablas = {
        "resumen": tabla_resumen(r),
        "comp_n_ciclos": tabla_comparacion(r.comparacion, "n_ciclos", True, r.elegidos["n_ciclos"]["familia"]),
        "comp_riego_m3ha": tabla_comparacion(r.comparacion, "riego_m3ha", False, r.elegidos["riego_m3ha"]["familia"]),
        "comp_inicio_min": tabla_comparacion(r.comparacion, "inicio_min", False, r.elegidos["inicio_min"]["familia"]),
        "plan": tabla_plan(r.comparacion),
        "rangos": tabla_rangos(r.comparacion),
        "por_turno": tabla_por_turno(r),
        "por_mes": tabla_por_mes(r),
        "confusion": tabla_confusion(r),
        "importancias": tabla_importancias(r),
        "pred_turno": r.pred_turno_test,
        "pred_ciclo": _redondear(_con_horas(r.pred_ciclo_test)),
        "plan_test": _redondear(_con_horas(r.plan_test)),
    }
    r.comparacion.to_csv(datos / "comparacion_modelos.csv", index=False)
    r.pred_turno_test.to_csv(datos / "predicciones_test_turno.csv", index=False)
    r.pred_ciclo_test.to_csv(datos / "predicciones_test_ciclo.csv", index=False)
    r.plan_test.to_csv(datos / "predicciones_test_plan.csv", index=False)
    (datos / "resumen.json").write_text(
        json.dumps({"corrida": r.info_corrida, "resumen": tablas["resumen"].to_dict(orient="records")},
                   indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tablas["historial"] = tabla_historial(carpeta.parent)
    if not tablas["historial"].empty:
        from riego_ml.utils.excel import write_excel

        write_excel(carpeta.parent.parent / "historial_entrenamientos.xlsx", {"Historial": tablas["historial"]})
    imagenes = generar_graficos(r, carpeta / "graficos")
    escribir_excel(r, tablas, imagenes, carpeta / "metricas_modelos.xlsx")
    if logger:
        logger.info("Reporte: %s (%d gráficos)", carpeta, len(imagenes))
    return carpeta
