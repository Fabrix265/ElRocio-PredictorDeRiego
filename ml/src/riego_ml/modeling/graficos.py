"""Gráficos del reporte de entrenamiento (PNG, también incrustados en el Excel).

Convenciones: un color fijo por familia de modelo en todos los gráficos, gris
neutro para la persistencia (es la referencia, no un modelo) y para lo real
observado; texto siempre en tinta neutra; una sola escala por eje.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRILLA = "#e4e3df"
REAL = "#8a8984"
COLORES = {
    "random_forest": "#2a78d6",
    "xgboost": "#eb6834",
    "lightgbm": "#1baf7a",
    "catboost": "#eda100",
    "transicion": "#e87ba4",
    "ordinal": "#008300",
    "persistencia_segura": "#6250d6",
    "dosis": "#e34948",
    "svr": "#8a8984",
    "mlp": "#8a8984",
    "persistencia": "#b5b4ae",
    "media_7d": "#b5b4ae",
    "semana_pasada": "#b5b4ae",
}
NOMBRES = {
    "random_forest": "Random Forest",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "catboost": "CatBoost",
    "transicion": "Transición (Markov)",
    "ordinal": "Logística ordinal",
    "persistencia_segura": "Persistencia salvo cambio seguro",
    "dosis": "Clasificador de dosis",
    "svr": "SVR / SVC",
    "mlp": "MLP",
    "persistencia": "Ref: persistencia (ayer)",
    "media_7d": "Ref: media 7 días",
    "semana_pasada": "Ref: semana pasada",
}
VALIDACION = "#86b6ef"
TEST = "#1c5cab"
AZUL_SEQ = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE,
    "savefig.facecolor": SUPERFICIE,
    "axes.edgecolor": GRILLA,
    "axes.labelcolor": TINTA_2,
    "axes.titlecolor": TINTA,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.labelsize": 10,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRILLA,
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": TINTA_2,
    "ytick.color": TINTA_2,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "font.family": "DejaVu Sans",
})


def _guardar(fig, carpeta: Path, nombre: str) -> Path:
    ruta = carpeta / f"{nombre}.png"
    fig.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return ruta


def _subtitulo(ax, texto: str) -> None:
    """Subtítulo debajo del título (el título se dibuja con ``pad`` extra)."""
    ax.set_title(ax.get_title(loc="left"), loc="left", pad=20)
    ax.text(0, 1.01, texto, transform=ax.transAxes, color=TINTA_2, fontsize=9, va="bottom")


# --------------------------------------------------------------------------- #
def comparacion_modelos(comparacion: pd.DataFrame, target: str, metrica: str, titulo: str,
                        elegido: str, mayor_es_mejor: bool, carpeta: Path, nombre: str) -> Path:
    """Barras agrupadas validación / test por modelo para la métrica principal."""
    d = comparacion[(comparacion["target"] == target) & comparacion["conjunto"].isin(["validacion", "test"])]
    tabla = d.pivot_table(index="modelo", columns="conjunto", values=metrica)
    orden = [m for m in NOMBRES if m in tabla.index]
    tabla = tabla.loc[orden]
    fig, ax = plt.subplots(figsize=(8.5, 1.2 + 0.62 * len(tabla)))
    y = np.arange(len(tabla))
    alto = 0.36
    ax.barh(y - alto / 2 - 0.01, tabla["validacion"], height=alto, color=VALIDACION, label="Validación")
    ax.barh(y + alto / 2 + 0.01, tabla["test"], height=alto, color=TEST, label="Test")
    for i, modelo in enumerate(tabla.index):
        for desplaz, conjunto in ((-alto / 2, "validacion"), (alto / 2, "test")):
            valor = tabla.loc[modelo, conjunto]
            ax.text(valor, i + desplaz, f" {valor:.3g}", va="center", fontsize=8, color=TINTA_2)
    ax.set_yticks(y, [NOMBRES[m] + ("  ★ elegido" if m == elegido else "") for m in tabla.index])
    for etiqueta, modelo in zip(ax.get_yticklabels(), tabla.index):
        if modelo == elegido:
            etiqueta.set_fontweight("bold")
            etiqueta.set_color(TINTA)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(metrica)
    ax.set_title(titulo)
    _subtitulo(ax, ("mayor es mejor" if mayor_es_mejor else "menor es mejor")
               + " · el elegido se decide en validación")
    ax.legend(loc="lower right")
    ax.set_xlim(0, tabla.to_numpy().max() * 1.15)
    return _guardar(fig, carpeta, nombre)


def matriz_confusion(real: pd.Series, pred: pd.Series, etiquetas: list[int], modelo: str,
                     carpeta: Path, nombre: str) -> Path:
    from matplotlib.colors import LinearSegmentedColormap

    cm = pd.crosstab(real, pred).reindex(index=etiquetas, columns=etiquetas, fill_value=0)
    pct = cm.div(cm.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    cmap = LinearSegmentedColormap.from_list("azul", AZUL_SEQ)
    ax.imshow(pct.to_numpy(), cmap=cmap, vmin=0, vmax=1)
    for i in range(len(etiquetas)):
        for j in range(len(etiquetas)):
            v = pct.iloc[i, j]
            ax.text(j, i, f"{v:.0%}\n({cm.iloc[i, j]})", ha="center", va="center", fontsize=8,
                    color="white" if v > 0.55 else TINTA)
    ax.set_xticks(range(len(etiquetas)), etiquetas)
    ax.set_yticks(range(len(etiquetas)), etiquetas)
    ax.set_xlabel("n_ciclos predicho")
    ax.set_ylabel("n_ciclos real")
    ax.grid(False)
    ax.set_title("Número de ciclos: real vs predicho (test)")
    _subtitulo(ax, f"{NOMBRES.get(modelo, modelo)} · % por fila (cuántos días reales de cada clase)")
    return _guardar(fig, carpeta, nombre)


def real_vs_predicho(real: pd.Series, pred: pd.Series, titulo: str, unidad: str, modelo: str,
                     carpeta: Path, nombre: str, escala: float = 1.0) -> Path:
    r, p = np.asarray(real, float) / escala, np.asarray(pred, float) / escala
    fig, ax = plt.subplots(figsize=(5.8, 5.4))
    ax.scatter(r, p, s=10, color=COLORES.get(modelo, TEST), alpha=0.35, linewidths=0)
    lim = [min(r.min(), p.min()), max(r.max(), p.max())]
    ax.plot(lim, lim, color=TINTA_2, linewidth=1.2, linestyle="--", label="predicción perfecta")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel(f"Real ({unidad})")
    ax.set_ylabel(f"Predicho ({unidad})")
    ax.set_title(titulo)
    rmse = np.sqrt(np.nanmean((p - r) ** 2))
    _subtitulo(ax, f"{NOMBRES.get(modelo, modelo)} · test · RMSE {rmse:.2f} {unidad}")
    ax.legend(loc="upper left")
    return _guardar(fig, carpeta, nombre)


def residuos(errores: dict[str, tuple[np.ndarray, str]], carpeta: Path, nombre: str) -> Path:
    fig, axes = plt.subplots(1, len(errores), figsize=(5.2 * len(errores), 3.8))
    for ax, (titulo, (err, unidad)) in zip(np.atleast_1d(axes), errores.items()):
        err = err[np.isfinite(err)]
        lim = np.nanpercentile(np.abs(err), 99)
        ax.hist(np.clip(err, -lim, lim), bins=40, color=TEST, edgecolor=SUPERFICIE, linewidth=0.6)
        ax.axvline(0, color=TINTA_2, linewidth=1.2)
        ax.set_title(titulo)
        _subtitulo(ax, f"error = predicho − real · sesgo medio {np.mean(err):+.2f} {unidad}")
        ax.set_xlabel(f"Error ({unidad})")
        ax.set_ylabel("Ciclos")
    return _guardar(fig, carpeta, nombre)


def serie_plan(plan_test: pd.DataFrame, carpeta: Path, nombre: str) -> Path:
    """Riego total por día (media de los turnos): real vs plan predicho."""
    d = plan_test.groupby("Fecha")[["riego_total_m3ha_real", "riego_total_m3ha_pred"]].mean()
    d = d.rolling(7, min_periods=1).mean()
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(d.index, d["riego_total_m3ha_real"], color=REAL, linewidth=2, label="Real")
    ax.plot(d.index, d["riego_total_m3ha_pred"], color=TEST, linewidth=2, label="Plan predicho")
    ax.set_ylabel("m3/ha por turno y día")
    ax.set_title("Riego total diario en el período de test")
    _subtitulo(ax, "media de los turnos · media móvil de 7 días")
    ax.legend(loc="upper left", ncols=2)
    fig.autofmt_xdate()
    return _guardar(fig, carpeta, nombre)


def error_por_grupo(tabla: pd.DataFrame, columnas: dict[str, str], titulo: str, carpeta: Path,
                    nombre: str, linea: bool = False) -> Path:
    """Un panel por métrica (cada una con su propia escala), sin doble eje."""
    fig, axes = plt.subplots(1, len(columnas), figsize=(4.6 * len(columnas), 3.6))
    for ax, (columna, etiqueta) in zip(np.atleast_1d(axes), columnas.items()):
        x = tabla.index.astype(str)
        if linea:
            ax.plot(x, tabla[columna], color=TEST, linewidth=2, marker="o", markersize=5)
            ax.tick_params(axis="x", rotation=45)
        else:
            ax.bar(x, tabla[columna], color=TEST, width=0.6)
            ax.grid(axis="x", visible=False)
        ax.set_title(etiqueta, fontsize=10)
        if "acierto" in columna.lower():
            ax.set_ylim(0, 1.05)
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        else:
            ax.set_ylim(0, tabla[columna].max() * 1.2)
    fig.suptitle(titulo, x=0.01, ha="left", fontsize=12, fontweight="bold", color=TINTA)
    fig.tight_layout()
    return _guardar(fig, carpeta, nombre)


def importancias(imp: dict[str, float], titulo: str, modelo: str, carpeta: Path, nombre: str,
                 top: int = 15) -> Path:
    serie = pd.Series(imp).sort_values(ascending=False).head(top)[::-1]
    fig, ax = plt.subplots(figsize=(7, 0.32 * len(serie) + 1.2))
    ax.barh(serie.index, serie.values, color=COLORES.get(modelo, TEST), height=0.6)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Importancia relativa")
    ax.set_title(titulo)
    _subtitulo(ax, f"{NOMBRES.get(modelo, modelo)} · top {len(serie)} variables")
    return _guardar(fig, carpeta, nombre)


def gantt_dia(plan_largo: pd.DataFrame, ciclos_reales: pd.DataFrame, fecha: pd.Timestamp,
              carpeta: Path, nombre: str) -> Path:
    """Horario de un día de test: ciclos reales vs plan predicho por turno."""
    pred = plan_largo[plan_largo["Fecha"] == fecha]
    real = ciclos_reales[ciclos_reales["Fecha"] == fecha]
    turnos = sorted(set(pred["Turno"]) | set(real["Turno"]))
    fig, ax = plt.subplots(figsize=(10, 0.75 * len(turnos) + 1.4))
    for i, turno in enumerate(turnos):
        for _, c in real[real["Turno"] == turno].iterrows():
            ax.barh(i - 0.18, c["duracion_min"] / 60, left=c["inicio_min"] / 60, height=0.32, color=REAL)
        for _, c in pred[pred["Turno"] == turno].iterrows():
            ax.barh(i + 0.18, c["duracion_min"] / 60, left=c["inicio_min"] / 60, height=0.32, color=TEST)
    ax.set_yticks(range(len(turnos)), turnos)
    ax.invert_yaxis()
    ax.set_xlim(0, 26)
    ax.set_xticks(range(0, 27, 2), [f"{h:02d}:00" for h in range(0, 27, 2)])
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Horario de riego del {fecha:%d/%m/%Y}: real vs plan predicho")
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=REAL, label="Real"), Patch(color=TEST, label="Plan predicho")],
              loc="lower right", ncols=2)
    _subtitulo(ax, "cada barra es un ciclo (inicio → fin)")
    return _guardar(fig, carpeta, nombre)
