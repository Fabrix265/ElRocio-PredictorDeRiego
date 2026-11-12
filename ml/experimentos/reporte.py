"""Excel y resumen en Markdown de los experimentos."""

from __future__ import annotations

import json

import pandas as pd

import exp_rangos

NOMBRES = {
    "accuracy": "Acierto exacto", "accuracy_pm1": "Acierto ±1", "acierto_sin_cambio": "Acierto días sin cambio",
    "acierto_con_cambio": "Acierto días con cambio", "propone_cambio": "% días que propone cambiar",
    "precision_cambio": "Cuando propone cambio, acierta", "acierto_4mas": "Acierto días de 4+ ciclos",
    "f1_macro": "F1 macro", "cohen_kappa": "Kappa", "mae_ciclos": "Error medio (ciclos)",
    "mae": "Error promedio", "medae": "Error mediano", "rmse": "RMSE", "r2": "R²", "mbe": "Sesgo",
    "dentro_1h": "% dentro de ±1 h", "dentro_2h": "% dentro de ±2 h", "franja_ok": "% franja acertada",
    "dur_mae": "Duración: error promedio (min)", "dur_medae": "Duración: error mediano (min)",
    "dur_rmse": "Duración: RMSE (min)", "dur_mbe": "Duración: sesgo (min)",
    "cobertura": "Cobertura", "ancho_medio": "Ancho medio",
}

GLOSARIO = [
    ("Períodos de desarrollo (dev)", "5 semestres entre mar-2023 y sep-2025. En cada uno el modelo aprende con todo lo "
     "anterior y se mide en ese semestre. El ganador se elige por el PROMEDIO de los 5."),
    ("Examen final (final)", "23-sep-2025 a 4-nov-2026 (el mismo test del modelo en uso). Se aprende con todo lo "
     "anterior al 15-sep-2025. Nunca se usa para elegir: solo confirma."),
    ("gana_a_actual_dev", "En cuántos de los 5 períodos de desarrollo fue mejor que el modelo en uso."),
    ("Acierto exacto", "% de turno-días con el n° de ciclos exacto."),
    ("Acierto ±1", "% de turno-días en que se equivocó como mucho en 1 ciclo."),
    ("Acierto días con cambio", "Solo los días en que el n° de ciclos cambió respecto de ayer: % acertados."),
    ("Acierto días sin cambio", "Días en que se repitió el n° de ayer: % acertados."),
    ("% días que propone cambiar", "Con qué frecuencia el modelo propone un n° distinto al de ayer."),
    ("Cuando propone cambio, acierta", "De las veces que propone cambiar, % en que el n° propuesto fue el real."),
    ("F1 macro", "Promedio del acierto por clase (1, 2, 3, 4, 5 ciclos) con el mismo peso para cada una."),
    ("Kappa", "Acierto por encima del azar (0 = azar, 1 = perfecto)."),
    ("Error promedio (MAE)", "Cuánto se aleja en promedio del valor real, en sus unidades (m3/ha o minutos)."),
    ("Error mediano", "La mitad de los casos se equivoca menos que esto."),
    ("RMSE", "Como el error promedio, pero castiga más los errores grandes."),
    ("R²", "Cuánto de la variación explica (0 = no mejor que el promedio, 1 = perfecto)."),
    ("Sesgo", "Si tiende a pasarse (+) o quedarse corto (−)."),
    ("% dentro de ±1 h / ±2 h", "% de ciclos cuya hora de inicio predicha cae a menos de 1 h / 2 h de la real."),
    ("% franja acertada", "% de ciclos en la franja correcta: 00-06, 06-12, 12-18 o 18-24 h."),
    ("Cobertura", "% de veces que el valor real cayó dentro del rango. Meta: 80 %."),
    ("Ancho medio", "Qué tan amplio es el rango en promedio (más angosto = más útil, si cubre)."),
    ("ESCENARIO", "Usa información que NO existe a la medianoche (p. ej. la hora real del 1er ciclo dada por el "
     "operador). Se informa para ver el potencial, nunca se elige."),
]


def _bonito(tabla: pd.DataFrame, descripciones: dict[str, str] | None = None) -> pd.DataFrame:
    t = tabla.copy()
    if descripciones is not None:
        t.insert(0, "Qué es", t.index.map(lambda n: descripciones.get(n, "")))
    ren = {}
    for c in t.columns:
        base, _, sufijo = c.rpartition("_")
        if sufijo in ("dev", "final") and base in NOMBRES:
            ren[c] = f"{NOMBRES[base]} ({sufijo})"
        elif c.endswith("_dev_std"):
            ren[c] = f"{NOMBRES.get(c[:-8], c[:-8])} (dev, desvío)"
    return t.rename(columns=ren)


def _md(tabla: pd.DataFrame, columnas: list[str], fmt: dict[str, str], max_filas: int = 12,
        incluir: list[str] | None = None) -> str:
    t = tabla.copy()
    filas = list(t.index[:max_filas])
    for extra in incluir or []:
        if extra in t.index and extra not in filas:
            filas.append(extra)
    t = t.loc[filas, [c for c in columnas if c in t.columns]]
    cab = "| Candidato | " + " | ".join(columnas) + " |"
    sep = "|---|" + "---|" * len(columnas)
    lineas = [cab, sep]
    for nombre, fila in t.iterrows():
        celdas = []
        for c in columnas:
            v = fila.get(c)
            celdas.append("—" if v is None or (isinstance(v, float) and pd.isna(v)) else
                          (format(v, fmt.get(c, ".3f")) if isinstance(v, (int, float)) else str(v)))
        lineas.append(f"| {nombre} | " + " | ".join(celdas) + " |")
    return "\n".join(lineas)


def _df_md(df: pd.DataFrame) -> str:
    def celda(v):
        return format(v, ".3f") if isinstance(v, float) else str(v)
    lineas = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lineas += ["| " + " | ".join(celda(v) for v in fila) + " |" for fila in df.itertuples(index=False)]
    return "\n".join(lineas)


def generar(carpeta, tablas: dict[str, pd.DataFrame], ganadores: dict[str, str], actuales: dict[str, str],
            reg: dict[str, dict], ajustados: dict, log) -> None:
    datos = carpeta / "datos"
    rangos = pd.read_csv(datos / "rangos.csv") if (datos / "rangos.csv").exists() else None
    plan = pd.read_csv(datos / "plan.csv") if (datos / "plan.csv").exists() else None
    ajuste = pd.read_csv(datos / "ajuste_hiper.csv") if (datos / "ajuste_hiper.csv").exists() else None

    md = ["# Experimentos del plan de riego — resumen", ""]
    hojas: dict[str, pd.DataFrame] = {}

    # Resumen ganador vs actual
    filas = []
    claves = {"n_ciclos": ["accuracy", "acierto_con_cambio", "accuracy_pm1"],
              "riego_m3ha": ["mae", "rmse", "dur_mae"], "inicio_min": ["mae", "dentro_1h", "dentro_2h", "franja_ok"]}
    for target, tabla in tablas.items():
        for rol, nombre in (("actual", actuales[target]), ("ganador", ganadores[target])):
            fila = {"Salida": target, "Rol": rol, "Candidato": nombre}
            for c in claves[target]:
                for s in ("dev", "final"):
                    if f"{c}_{s}" in tabla:
                        fila[f"{NOMBRES[c]} ({s})"] = tabla.loc[nombre, f"{c}_{s}"]
            filas.append(fila)
    hojas["Resumen"] = pd.DataFrame(filas)

    fmt = {"gana_a_actual_dev": "s"}
    secciones = {
        "n_ciclos": ("N_ciclos", ["accuracy_dev", "accuracy_final", "acierto_con_cambio_dev", "acierto_con_cambio_final",
                                  "acierto_sin_cambio_final", "propone_cambio_final", "precision_cambio_final",
                                  "accuracy_pm1_final", "gana_a_actual_dev"]),
        "inicio_min": ("Hora_inicio", ["mae_dev", "mae_final", "rmse_dev", "medae_final", "dentro_1h_final", "dentro_2h_final",
                                       "franja_ok_final", "r2_final", "mbe_final", "gana_a_actual_dev"]),
        "riego_m3ha": ("M3ha_y_duracion", ["mae_dev", "mae_final", "medae_final", "rmse_dev", "rmse_final", "r2_final",
                                           "mbe_final", "dur_mae_dev", "dur_mae_final", "gana_a_actual_dev"]),
    }
    for target, (hoja, cols) in secciones.items():
        if target not in tablas:
            continue
        descr = {n: c.descripcion for n, c in reg[target].items()}
        hojas[hoja] = _bonito(tablas[target], descr).reset_index().rename(columns={"candidato": "Candidato"})
        md += [f"## {hoja}", "", f"Ganador en desarrollo: **{ganadores[target]}** · Actual: {actuales[target]}", "",
               _md(tablas[target], cols, fmt, incluir=[actuales[target], *[n for n in tablas[target].index
                                                                          if "ESCENARIO" in n]]), ""]

    if rangos is not None:
        rt = exp_rangos.resumir(rangos)
        eleg = exp_rangos.elegir(rt)
        hojas["Rangos"] = rt
        md += ["## Rangos", "", f"Elegidos: {eleg}", "", _df_md(rt), ""]
    if plan is not None:
        dev = plan[plan["periodo"].str.startswith("dev")].groupby("combinacion").mean(numeric_only=True)
        fin = plan[plan["periodo"] == "final"].set_index("combinacion")
        cols = ["acierto_n_ciclos", "riego_total_m3ha_mae", "duracion_total_min_mae", "inicio_primer_min_mae",
                "fin_ultimo_min_mae"]
        pt = dev[cols].add_suffix("_dev").join(fin[cols].add_suffix("_final"))
        hojas["Plan_completo"] = pt.reset_index()
        md += ["## Plan completo (por turno y día)", "", _df_md(pt.reset_index()), ""]
    if ajuste is not None:
        hojas["Ajuste_hiper"] = ajuste
        md += ["## Hiperparámetros elegidos (búsqueda en dev3–dev5)", "", "```json",
               json.dumps(ajustados, indent=2, ensure_ascii=False), "```", ""]
    for target in tablas:
        ruta = datos / f"{target}.csv"
        if ruta.exists():
            hojas[f"Detalle_{target}"[:31]] = pd.read_csv(ruta)
    if rangos is not None:
        hojas["Detalle_rangos"] = rangos
    if plan is not None:
        hojas["Detalle_plan"] = plan
    hojas["Glosario"] = pd.DataFrame(GLOSARIO, columns=["Término", "Significado"])

    ruta_xlsx = carpeta / "comparativa_experimentos.xlsx"
    with pd.ExcelWriter(ruta_xlsx, engine="openpyxl") as w:
        for nombre, df in hojas.items():
            df.to_excel(w, sheet_name=nombre[:31], index=False)
            hoja = w.sheets[nombre[:31]]
            for col in hoja.columns:
                ancho = max(len(str(c.value or "")) for c in col[:60])
                hoja.column_dimensions[col[0].column_letter].width = min(max(10, ancho + 2), 60)
            hoja.freeze_panes = "B2"
    (carpeta / "resumen.md").write_text("\n".join(md), encoding="utf-8")
    log.info("Reporte: %s", ruta_xlsx)
