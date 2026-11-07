"""Paso 3 - Entrena, compara y selecciona los modelos del plan de riego.

Protocolo
---------
* Split temporal por fechas: train -> (gap) -> validación -> (gap) -> test.
* Para cada target (``n_ciclos``, ``riego_m3ha``, ``inicio_min``) se entrenan
  las familias habilitadas (RF, XGBoost, SVR, MLP) solo con train.
* El modelo de cada target se elige por su desempeño en VALIDACIÓN
  (F1 macro para ``n_ciclos``, RMSE para los regresores). El test solo se usa
  para reportar, nunca para elegir.
* Referencia "persistencia": repetir lo que hizo el mismo turno/ciclo el día
  anterior. Un modelo que no la supera no aporta valor.
* Se evalúa el plan completo en test (n_ciclos predicho -> ciclos -> horario).
* El modelo final se reentrena con todos los datos y se guarda como un único
  ``PlanRiego`` en ``modelos_dir/plan_riego/modelo_plan_riego.joblib``.
"""

from __future__ import annotations

import time
import warnings
from datetime import datetime
from typing import Any

import joblib
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.model_selection import RandomizedSearchCV

from riego_ml.config import Config
from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.dataset.preparar import cargar_dataset
from riego_ml.modeling import metricas
from riego_ml.modeling.estimadores import (
    PERSISTENCIA,
    PERSISTENCIA_NOMBRE,
    Persistencia,
    crear_estimador,
    espacio_busqueda,
    importancias,
    prefijo_params,
)
from riego_ml.modeling.planificador import PlanRiego, plan_ancho
from riego_ml.modeling.split import cortes_temporales, folds_temporales
from riego_ml.utils.excel import dict_to_frame, write_excel
from riego_ml.utils.io import save_json
from riego_ml.utils.reproducibility import environment_info, set_seeds

NOMBRE_BUNDLE = "modelo_plan_riego.joblib"


class Entrenador:
    def __init__(self, config: Config, logger):
        self.config = config
        self.logger = logger
        self.filas: list[dict[str, Any]] = []
        self.elegidos: dict[str, dict[str, Any]] = {}
        self.importancias: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ #
    def ejecutar(self) -> dict[str, Any]:
        cfg = self.config
        set_seeds(cfg.seed)
        if not cfg.modelos_habilitados():
            raise ValueError("No hay modelos habilitados en la configuración.")

        ds = cargar_dataset(cfg.rutas.processed_dir)
        cols = ds.columnas
        self.categoricas = list(cols["categoricas"])
        self.f_turno = list(cols["features_turno"])
        self.f_ciclo = list(cols["features_ciclo"])
        maxc = cfg.plan.max_ciclos

        td = ds.turno_dia.copy()
        td["n_ciclos_clase"] = td["n_ciclos"].clip(upper=maxc).astype(int)
        ci = ds.ciclos[ds.ciclos["n_ciclos"] <= maxc].copy()
        self.ciclos_hist = ds.ciclos

        self.cortes = cortes_temporales(td["Fecha"], cfg.split.test, cfg.split.validacion, cfg.split.gap_dias)
        td["conjunto"] = self.cortes.asignar(td["Fecha"])
        ci["conjunto"] = self.cortes.asignar(ci["Fecha"])
        self._log_split(td, ci)

        etiquetas = list(range(1, maxc + 1))
        self._comparar("n_ciclos", "clasificacion", td, "n_ciclos_clase", self.f_turno, etiquetas)
        self._comparar("riego_m3ha", "regresion", ci, "riego_m3ha", self.f_ciclo)
        self._comparar("inicio_min", "regresion", ci, "inicio_min", self.f_ciclo)

        train = ci[ci["conjunto"] == "train"]
        self.min_por_m3ha_train = self._min_por_m3ha(train)
        self._evaluar_derivados(ci)
        plan_test = self._evaluar_plan(td, ci)

        plan_final = self._reentrenar_final(td, ci)
        destino = cfg.rutas.modelos_dir / "plan_riego"
        destino.mkdir(parents=True, exist_ok=True)
        joblib.dump(plan_final, destino / NOMBRE_BUNDLE, compress=3)
        save_json(destino / "metadata.json", plan_final.metadata)
        self._guardar_reportes(plan_test)

        resumen = {
            "elegidos": {k: v["familia"] for k, v in self.elegidos.items()},
            "modelo": str(destino / NOMBRE_BUNDLE),
            "reportes": str(cfg.rutas.reportes_dir),
        }
        self.logger.info("Entrenamiento finalizado: %s", resumen)
        return resumen

    # ------------------------------------------------------------------ #
    def _mascara_eval(self, df: pd.DataFrame) -> pd.Series:
        if self.config.excluir_dias_incompletos_eval:
            return df["dia_incompleto"].fillna(0) == 0
        return pd.Series(True, index=df.index)

    def _params(self, familia: str, tarea: str) -> dict[str, Any]:
        modelo = self.config.modelos[familia]
        return dict(modelo.clasificacion if tarea == "clasificacion" else modelo.regresion)

    def _numericas(self, features: list[str]) -> list[str]:
        return [c for c in features if c not in self.categoricas]

    def _crear(self, nombre: str, familia: str, tarea: str, features: list[str], params: dict[str, Any]):
        if familia == PERSISTENCIA_NOMBRE:
            columna, grupos = PERSISTENCIA[nombre]
            return Persistencia(columna, grupos, tarea)
        return crear_estimador(
            familia, tarea, params, self.categoricas, self._numericas(features), self.config.seed
        )

    def _ajustar(self, estimador, X: pd.DataFrame, y: pd.Series):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            warnings.simplefilter("ignore", UserWarning)
            return estimador.fit(X, y)

    def _buscar(self, nombre, familia, tarea, features, train, target) -> dict[str, Any]:
        """Búsqueda aleatoria de hiperparámetros con folds temporales (opcional)."""
        tuning = self.config.tuning
        base = self._crear(nombre, familia, tarea, features, self._params(familia, tarea))
        prefijo = prefijo_params(base)
        espacio = {prefijo + k: v for k, v in espacio_busqueda(familia, tarea).items()}
        busqueda = RandomizedSearchCV(
            base,
            espacio,
            n_iter=tuning.n_iter,
            cv=folds_temporales(train["Fecha"], tuning.folds, self.config.split.gap_dias),
            scoring="f1_macro" if tarea == "clasificacion" else "neg_root_mean_squared_error",
            random_state=self.config.seed,
            n_jobs=tuning.n_jobs,
            refit=False,
        )
        self._ajustar(busqueda, train[features].reset_index(drop=True), train[target].reset_index(drop=True))
        mejores = {k[len(prefijo):]: v for k, v in busqueda.best_params_.items()}
        self.logger.info("    tuning %s/%s -> %s", target, familia, mejores)
        return {**self._params(familia, tarea), **mejores}

    def _metricas(self, tarea, y, pred, etiquetas=None) -> dict[str, Any]:
        if tarea == "clasificacion":
            return metricas.clasificacion(y, pred, etiquetas)
        return metricas.regresion(y, pred)

    def _registrar(self, target, modelo, conjunto, valores: dict[str, Any], **extra) -> None:
        fila = {"target": target, "modelo": modelo, "conjunto": conjunto, **extra}
        fila.update({k: v for k, v in valores.items() if k != "confusion"})
        self.filas.append(fila)

    # ------------------------------------------------------------------ #
    def _comparar(self, nombre, tarea, df, target, features, etiquetas=None) -> None:
        self.logger.info("Target %s (%s): %d features", nombre, tarea, len(features))
        train = df[df["conjunto"] == "train"]
        evaluacion = {c: df[(df["conjunto"] == c) & self._mascara_eval(df)] for c in ("validacion", "test")}
        candidatos = {}
        familias = self.config.modelos_habilitados()
        if self.config.incluir_persistencia:
            familias = [*familias, PERSISTENCIA_NOMBRE]
        for familia in familias:
            inicio = time.time()
            es_ml = familia != PERSISTENCIA_NOMBRE
            params = self._params(familia, tarea) if es_ml else {}
            if self.config.tuning.habilitado and es_ml:
                params = self._buscar(nombre, familia, tarea, features, train, target)
            estimador = self._ajustar(
                self._crear(nombre, familia, tarea, features, params), train[features], train[target]
            )
            segundos = round(time.time() - inicio, 1)
            puntajes = {}
            for conjunto, datos in evaluacion.items():
                valores = self._metricas(tarea, datos[target], estimador.predict(datos[features]), etiquetas)
                puntajes[conjunto] = valores
                self._registrar(nombre, familia, conjunto, valores, segundos=segundos)
            clave = "f1_macro" if tarea == "clasificacion" else "rmse"
            score = puntajes["validacion"][clave]
            candidatos[familia] = (score, estimador, params, puntajes)
            self.logger.info(
                "  %-13s val %s=%.4f | test %s=%.4f (%.0fs)",
                familia, clave, score, clave, puntajes["test"][clave], segundos,
            )
        mejor = (max if tarea == "clasificacion" else min)(candidatos, key=lambda f: candidatos[f][0])
        score, estimador, params, puntajes = candidatos[mejor]
        self.elegidos[nombre] = {
            "familia": mejor,
            "tarea": tarea,
            "target": target,
            "features": features,
            "params": params,
            "estimador_train": estimador,
            "validacion": puntajes["validacion"],
            "test": puntajes["test"],
        }
        imp = importancias(estimador)
        if imp:
            self.importancias[nombre] = imp
        self.logger.info("  -> elegido para %s: %s", nombre, mejor)

    @staticmethod
    def _min_por_m3ha(ciclos: pd.DataFrame) -> dict[str, float]:
        ratio = ciclos["duracion_min"] / ciclos["riego_m3ha"]
        return ratio.groupby(ciclos["Turno"]).median().round(4).to_dict()

    @staticmethod
    def _area(ciclos: pd.DataFrame) -> dict[str, float]:
        return ciclos.groupby("Turno")["area_ha"].median().round(4).to_dict()

    def _evaluar_derivados(self, ci) -> None:
        """Duración y fin derivados (con el n_ciclos real) en test."""
        test = ci[(ci["conjunto"] == "test") & self._mascara_eval(ci)]
        m3ha = self.elegidos["riego_m3ha"]["estimador_train"].predict(test[self.f_ciclo])
        inicio = self.elegidos["inicio_min"]["estimador_train"].predict(test[self.f_ciclo])
        ratio = test["Turno"].map(self.min_por_m3ha_train).to_numpy()
        duracion = m3ha * ratio
        modelo = f"{self.elegidos['riego_m3ha']['familia']} + caudal del turno"
        self._registrar("duracion_min (derivada)", modelo, "test", metricas.regresion(test["duracion_min"], duracion))
        self._registrar("duracion_min (con m3ha real)", "caudal del turno", "test",
                        metricas.regresion(test["duracion_min"], test["riego_m3ha"].to_numpy() * ratio))
        self._registrar("fin_min (derivado)", modelo, "test", metricas.regresion(test["fin_min"], inicio + duracion))

    def _plan(self, modelos: dict[str, Any], ciclos: pd.DataFrame, metadata=None) -> PlanRiego:
        return PlanRiego(
            modelo_n_ciclos=modelos["n_ciclos"],
            modelo_m3ha=modelos["riego_m3ha"],
            modelo_inicio=modelos["inicio_min"],
            features_turno=self.f_turno,
            features_ciclo=self.f_ciclo,
            max_ciclos=self.config.plan.max_ciclos,
            min_por_m3ha=self._min_por_m3ha(ciclos),
            area_ha=self._area(ciclos),
            rango_m3ha=(float(ciclos["riego_m3ha"].quantile(0.001)), float(ciclos["riego_m3ha"].quantile(0.999))),
            pausa_min=self.config.plan.pausa_min_entre_ciclos,
            elegidos={k: v["familia"] for k, v in self.elegidos.items()},
            metadata=metadata or {},
        )

    def _evaluar_plan(self, td, ci) -> pd.DataFrame:
        """Plan completo en test: n_ciclos predicho -> ciclos -> horario."""
        modelos = {k: v["estimador_train"] for k, v in self.elegidos.items()}
        plan = self._plan(modelos, ci[ci["conjunto"] == "train"])
        test = td[(td["conjunto"] == "test") & self._mascara_eval(td)]
        entrada = test[[*CLAVES_TD, *[c for c in self.f_turno if c not in CLAVES_TD]]]
        predicho = plan.predecir(entrada, self.ciclos_hist)
        resumen = (
            predicho.groupby(CLAVES_TD)
            .agg(n_ciclos_pred=("n_ciclos", "first"), riego_total_m3ha_pred=("riego_m3ha", "sum"),
                 duracion_total_min_pred=("duracion_min", "sum"), inicio_primer_min_pred=("inicio_min", "min"),
                 fin_ultimo_min_pred=("fin_min", "max"))
            .reset_index()
        )
        comparado = test[[*CLAVES_TD, "n_ciclos", "riego_total_m3ha", "duracion_total_min",
                          "inicio_primer_min", "fin_ultimo_min"]].merge(resumen, on=CLAVES_TD)
        for target in ("riego_total_m3ha", "duracion_total_min", "inicio_primer_min", "fin_ultimo_min"):
            self._registrar(f"plan: {target}", "plan completo", "test",
                            metricas.regresion(comparado[target], comparado[f"{target}_pred"]))
        acierto = (comparado["n_ciclos"].clip(upper=self.config.plan.max_ciclos) == comparado["n_ciclos_pred"]).mean()
        self.logger.info("Plan en test: acierto n_ciclos=%.3f | RMSE total m3/ha=%.2f", acierto,
                         metricas.regresion(comparado["riego_total_m3ha"], comparado["riego_total_m3ha_pred"])["rmse"])
        ancho = plan_ancho(predicho, self.config.plan.max_ciclos)
        return comparado.merge(ancho.drop(columns=["n_ciclos", "riego_total_m3ha", "duracion_total_min"]),
                               on=CLAVES_TD, how="left")

    def _reentrenar_final(self, td, ci) -> PlanRiego:
        """Reentrena los modelos elegidos con todos los datos disponibles."""
        self.logger.info("Reentrenando los modelos elegidos con todos los datos...")
        modelos = {}
        for nombre, info in self.elegidos.items():
            datos = td if info["tarea"] == "clasificacion" else ci
            estimador = self._crear(nombre, info["familia"], info["tarea"], info["features"], info["params"])
            modelos[nombre] = self._ajustar(estimador, datos[info["features"]], datos[info["target"]])
        metadata = {
            "entrenado": datetime.now().isoformat(timespec="seconds"),
            "rango_datos": f"{td['Fecha'].min():%Y-%m-%d} a {td['Fecha'].max():%Y-%m-%d}",
            "turno_dias": len(td),
            "ciclos": len(ci),
            "elegidos": {
                k: {"familia": v["familia"], "params": v["params"],
                    "validacion": {m: x for m, x in v["validacion"].items() if m != "confusion"},
                    "test": {m: x for m, x in v["test"].items() if m != "confusion"}}
                for k, v in self.elegidos.items()
            },
            "split": self.cortes.to_dict(),
            "features_turno": self.f_turno,
            "features_ciclo": self.f_ciclo,
            "config": self.config.to_dict(),
            "entorno": environment_info(),
        }
        return self._plan(modelos, ci, metadata)

    # ------------------------------------------------------------------ #
    def _log_split(self, td, ci) -> None:
        self.logger.info("Split temporal: %s", self.cortes.to_dict())
        for conjunto in ("train", "validacion", "test", "gap"):
            self.logger.info("  %-10s turno-días=%5d ciclos=%6d", conjunto,
                             int((td["conjunto"] == conjunto).sum()), int((ci["conjunto"] == conjunto).sum()))

    def _guardar_reportes(self, plan_test: pd.DataFrame) -> None:
        carpeta = self.config.rutas.reportes_dir
        carpeta.mkdir(parents=True, exist_ok=True)
        comparacion = pd.DataFrame(self.filas)
        resumen = pd.DataFrame([
            {"target": k, "modelo_elegido": v["familia"],
             **{f"val_{m}": x for m, x in v["validacion"].items() if m in ("f1_macro", "accuracy", "rmse", "mae", "r2")},
             **{f"test_{m}": x for m, x in v["test"].items() if m in ("f1_macro", "accuracy", "accuracy_pm1", "rmse", "mae", "r2")},
             "params": str(v["params"])}
            for k, v in self.elegidos.items()
        ])
        etiquetas = list(range(1, self.config.plan.max_ciclos + 1))
        confusion = pd.DataFrame(
            self.elegidos["n_ciclos"]["test"]["confusion"],
            index=[f"real_{e}" for e in etiquetas], columns=[f"pred_{e}" for e in etiquetas],
        ).reset_index(names="n_ciclos")
        imp = pd.DataFrame(
            [(t, f, round(v, 5)) for t, d in self.importancias.items() for f, v in list(d.items())[:25]],
            columns=["target", "feature", "importancia"],
        )
        plan_test.to_csv(carpeta / "predicciones_test_plan.csv", index=False)
        comparacion.to_csv(carpeta / "comparacion_modelos.csv", index=False)
        write_excel(carpeta / "metricas_modelos.xlsx", {
            "Resumen": resumen,
            "Comparacion": comparacion.round(4),
            "Confusion_n_ciclos": confusion,
            "Importancias": imp,
            "Plan_test": plan_test.round(2),
            "Split": dict_to_frame(self.cortes.to_dict(), "Corte", "Fecha"),
        })
        save_json(carpeta / "metricas.json", {
            "resumen": resumen.to_dict(orient="records"),
            "comparacion": comparacion.to_dict(orient="records"),
            "split": self.cortes.to_dict(),
        })
        self.logger.info("Reportes en %s", carpeta)


def entrenar(config: Config, logger) -> dict[str, Any]:
    return Entrenador(config, logger).ejecutar()
