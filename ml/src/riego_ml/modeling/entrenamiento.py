"""Paso 3 - Entrena, compara y selecciona los modelos del plan de riego.

Protocolo
---------
* Split temporal por fechas: train -> (gap) -> validación -> (gap) -> test.
* Para cada target (``n_ciclos``, ``riego_m3ha``, ``inicio_min``) se entrenan
  las familias habilitadas (RF, XGBoost, SVR, MLP) solo con train, y la
  persistencia ("repetir lo de ayer") compite como un candidato más.
* El modelo de cada target se elige por su desempeño en VALIDACIÓN
  (F1 macro para ``n_ciclos``, RMSE para los regresores). El test solo se usa
  para reportar, nunca para elegir.
* Se evalúa el plan completo en test (n_ciclos predicho -> ciclos -> horario).
* El modelo final se reentrena con todos los datos y se guarda como un único
  ``PlanRiego`` en ``modelos_dir/plan_riego/modelo_plan_riego.joblib``.
* Los reportes de cada corrida quedan en
  ``reportes_dir/entrenamientos/<AAAA-MM-DD_HHMM>/`` (Excel, gráficos y CSV).
"""

from __future__ import annotations

import shutil
import time
import warnings
from datetime import datetime
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.model_selection import RandomizedSearchCV

from riego_ml.config import Config
from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.dataset.preparar import cargar_dataset
from riego_ml.modeling import metricas
from riego_ml.modeling.especiales import (
    REFERENCIAS,
    ClasificadorDosis,
    OrdinalLogistico,
    Persistencia,
    PersistenciaSegura,
    RangoCuantiles,
    TransicionNCiclos,
)
from riego_ml.modeling.estimadores import (
    FAMILIAS,
    crear_estimador,
    espacio_busqueda,
    importancias,
    prefijo_params,
)
from riego_ml.modeling.planificador import COLUMNA_CAUDAL, PlanRiego
from riego_ml.modeling.reporte import ResultadosEntrenamiento, generar_reporte
from riego_ml.modeling.split import cortes_temporales, folds_temporales
from riego_ml.utils.io import save_json
from riego_ml.utils.reproducibility import environment_info, set_seeds

NOMBRE_BUNDLE = "modelo_plan_riego.joblib"
DESCRIPCION_TARGET = {
    "n_ciclos": "Número de ciclos del turno en el día",
    "riego_m3ha": "Volumen de cada ciclo (m3/ha)",
    "inicio_min": "Hora de inicio de cada ciclo (min desde 00:00)",
}


class Entrenador:
    def __init__(self, config: Config, logger):
        self.config = config
        self.logger = logger
        self.filas: list[dict[str, Any]] = []
        self.elegidos: dict[str, dict[str, Any]] = {}
        self.importancias: dict[str, dict[str, dict[str, float]]] = {}
        self.pred_test: dict[str, dict[str, np.ndarray]] = {}
        self.inicio_corrida = datetime.now()

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
        self.features_extendidas = bool(cols.get("features_extendidas", False))
        maxc = cfg.plan.max_ciclos

        td = ds.turno_dia.copy()
        td["n_ciclos_clase"] = td["n_ciclos"].clip(upper=maxc).astype(int)
        ci = ds.ciclos[ds.ciclos["n_ciclos"] <= maxc].copy()
        self.ciclos_hist = ds.ciclos

        self.cortes = cortes_temporales(td["Fecha"], cfg.split.test, cfg.split.validacion, cfg.split.gap_dias)
        td["conjunto"] = self.cortes.asignar(td["Fecha"])
        ci["conjunto"] = self.cortes.asignar(ci["Fecha"])
        self._log_split(td, ci)

        self.etiquetas = list(range(1, maxc + 1))
        self._comparar("n_ciclos", "clasificacion", td, "n_ciclos_clase", self.f_turno)
        self._comparar("riego_m3ha", "regresion", ci, "riego_m3ha", self.f_ciclo)
        self._comparar("inicio_min", "regresion", ci, "inicio_min", self.f_ciclo)

        self.min_por_m3ha_train = self._min_por_m3ha(ci[ci["conjunto"] == "train"])
        pred_turno, pred_ciclo = self._tablas_prediccion_test(td, ci)
        self._evaluar_rangos(ci)
        plan_test, plan_largo = self._evaluar_plan(td, ci)

        plan_final = self._reentrenar_final(td, ci)
        # Cada entrenamiento queda versionado; "actual" es el que usa predecir.py.
        version = self.inicio_corrida.strftime("%Y-%m-%d_%H%M")
        raiz = cfg.rutas.modelos_dir / "plan_riego"
        destino = raiz / "versiones" / version
        destino.mkdir(parents=True, exist_ok=True)
        joblib.dump(plan_final, destino / NOMBRE_BUNDLE, compress=3)
        save_json(destino / "metadata.json", plan_final.metadata)
        actual = raiz / "actual"
        actual.mkdir(parents=True, exist_ok=True)
        for archivo in (NOMBRE_BUNDLE, "metadata.json"):
            shutil.copy2(destino / archivo, actual / archivo)

        carpeta = cfg.rutas.reportes_dir / "entrenamientos" / self.inicio_corrida.strftime("%Y-%m-%d_%H%M")
        resultados = ResultadosEntrenamiento(
            comparacion=pd.DataFrame(self.filas),
            elegidos={k: {c: v[c] for c in ("familia", "tarea", "params", "validacion", "test")}
                      for k, v in self.elegidos.items()},
            descripcion_targets=DESCRIPCION_TARGET,
            importancias=self.importancias,
            pred_turno_test=pred_turno,
            pred_ciclo_test=pred_ciclo,
            plan_test=plan_test,
            plan_test_largo=plan_largo,
            ciclos_reales=ci,
            etiquetas=self.etiquetas,
            info_corrida=self._info_corrida(td, ci, destino / NOMBRE_BUNDLE),
            features={"turno": self.f_turno, "ciclo": self.f_ciclo,
                      "excluidas": cols.get("excluidas_del_modelo", [])},
        )
        generar_reporte(resultados, carpeta, self.logger)

        resumen = {
            "elegidos": {k: v["familia"] for k, v in self.elegidos.items()},
            "modelo": str(destino / NOMBRE_BUNDLE),
            "reporte": str(carpeta),
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

    def _candidatos(self, nombre: str) -> list[str]:
        """Modelos que compiten para un target: ML habilitados + especiales + referencias."""
        esp = self.config.especiales
        candidatos = list(self.config.modelos_habilitados())
        if nombre == "n_ciclos":
            candidatos += [m for m, activo in (("transicion", esp.transicion), ("ordinal", esp.ordinal),
                                                ("persistencia_segura", esp.persistencia_segura)) if activo]
        if nombre == "riego_m3ha" and esp.dosis:
            candidatos.append("dosis")
        # La persistencia siempre compite: es la vara mínima.
        referencias = list(REFERENCIAS[nombre]) if esp.referencias else ["persistencia"]
        return candidatos + referencias

    def _crear(self, nombre: str, familia: str, tarea: str, features: list[str], params: dict[str, Any]):
        numericas = [c for c in features if c not in self.categoricas]
        seed = self.config.seed
        lgbm_clf = dict(self.config.modelos["lightgbm"].clasificacion) if "lightgbm" in self.config.modelos else {}
        if familia in REFERENCIAS[nombre]:
            columna, grupos = REFERENCIAS[nombre][familia]
            return Persistencia(columna, grupos, tarea)
        if familia == "transicion":
            return TransicionNCiclos()
        if familia == "ordinal":
            return OrdinalLogistico(self.categoricas, numericas)
        if familia == "persistencia_segura":
            return PersistenciaSegura(self.categoricas, numericas, lgbm_clf, seed)
        if familia == "dosis":
            params_dosis = {k: v for k, v in lgbm_clf.items() if k != "class_weight"}
            return ClasificadorDosis(self.categoricas, numericas, params_dosis, seed=seed)
        return crear_estimador(familia, tarea, params, self.categoricas, numericas, seed)

    @staticmethod
    def _features_modelo(estimador, features: list[str]) -> list[str]:
        """Features del target + columnas extra que necesita el modelo (referencias)."""
        extra = getattr(estimador, "columnas_requeridas", [])
        return list(dict.fromkeys([*features, *extra]))

    @staticmethod
    def _ajustar(estimador, X: pd.DataFrame, y: pd.Series):
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

    def _metricas(self, tarea, y, pred) -> dict[str, Any]:
        if tarea == "clasificacion":
            return metricas.clasificacion(y, pred, self.etiquetas)
        return metricas.regresion(y, pred)

    def _registrar(self, target, modelo, conjunto, valores: dict[str, Any], **extra) -> None:
        fila = {"target": target, "modelo": modelo, "conjunto": conjunto, **extra}
        fila.update({k: v for k, v in valores.items() if k != "confusion"})
        self.filas.append(fila)

    # ------------------------------------------------------------------ #
    def _comparar(self, nombre, tarea, df, target, features) -> None:
        self.logger.info("Target %s (%s): %d features", nombre, tarea, len(features))
        train = df[df["conjunto"] == "train"]
        evaluacion = {c: df[(df["conjunto"] == c) & self._mascara_eval(df)] for c in ("validacion", "test")}
        familias = self._candidatos(nombre)
        clave = "f1_macro" if tarea == "clasificacion" else "rmse"
        candidatos = {}
        self.pred_test[nombre] = {}
        self.importancias[nombre] = {}
        for familia in familias:
            inicio = time.time()
            es_ml = familia in FAMILIAS
            params = self._params(familia, tarea) if es_ml else {}
            if self.config.tuning.habilitado and es_ml:
                params = self._buscar(nombre, familia, tarea, features, train, target)
            estimador = self._crear(nombre, familia, tarea, features, params)
            columnas = self._features_modelo(estimador, features)
            try:
                estimador = self._ajustar(estimador, train[columnas], train[target])
            except Exception as exc:  # noqa: BLE001 - un candidato que falla no frena al resto
                self.logger.warning("  %-20s falló: %s", familia, exc)
                continue
            segundos = round(time.time() - inicio, 1)
            puntajes = {}
            for conjunto, datos in evaluacion.items():
                pred = estimador.predict(datos[columnas])
                if conjunto == "test":
                    self.pred_test[nombre][familia] = np.asarray(pred)
                puntajes[conjunto] = self._metricas(tarea, datos[target], pred)
                self._registrar(nombre, familia, conjunto, puntajes[conjunto], segundos=segundos)
            candidatos[familia] = (puntajes["validacion"][clave], estimador, params, puntajes, columnas)
            imp = importancias(estimador)
            if imp:
                self.importancias[nombre][familia] = imp
            self.logger.info(
                "  %-20s val %s=%.4f | test %s=%.4f (%.0fs)",
                familia, clave, puntajes["validacion"][clave], clave, puntajes["test"][clave], segundos,
            )
        # En empate gana el más simple: las referencias van al final de la lista.
        signo = 1 if tarea == "clasificacion" else -1
        mejor = max(reversed(list(candidatos)), key=lambda f: round(signo * candidatos[f][0], 9))
        _, estimador, params, puntajes, columnas = candidatos[mejor]
        self.elegidos[nombre] = {
            "familia": mejor, "tarea": tarea, "target": target, "features": columnas, "params": params,
            "estimador_train": estimador, "validacion": puntajes["validacion"], "test": puntajes["test"],
        }
        self.logger.info("  -> elegido para %s: %s", nombre, mejor)

    @staticmethod
    def _min_por_m3ha(ciclos: pd.DataFrame) -> dict[str, float]:
        ratio = ciclos["duracion_min"] / ciclos["riego_m3ha"]
        return ratio.groupby(ciclos["Turno"]).median().round(4).to_dict()

    @staticmethod
    def _area(ciclos: pd.DataFrame) -> dict[str, float]:
        return ciclos.groupby("Turno")["area_ha"].median().round(4).to_dict()

    def _tablas_prediccion_test(self, td, ci) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Observado vs predicho en test (cada familia + el elegido) y derivados."""
        t = td[(td["conjunto"] == "test") & self._mascara_eval(td)]
        turno = t[[*CLAVES_TD, "dia_incompleto"]].assign(n_ciclos_real=t["n_ciclos_clase"].to_numpy())
        for familia, pred in self.pred_test["n_ciclos"].items():
            turno[f"n_ciclos_{familia}"] = pred
        turno["n_ciclos_pred"] = turno[f"n_ciclos_{self.elegidos['n_ciclos']['familia']}"]

        c = ci[(ci["conjunto"] == "test") & self._mascara_eval(ci)]
        ciclo = c[[*CLAVES_TD, "Ciclo", "n_ciclos", "riego_m3ha", "inicio_min", "duracion_min", "fin_min",
                   COLUMNA_CAUDAL]].copy()
        ciclo = ciclo.rename(columns={"riego_m3ha": "riego_m3ha_real", "inicio_min": "inicio_min_real",
                                      "duracion_min": "duracion_min_real", "fin_min": "fin_min_real"})
        for target in ("riego_m3ha", "inicio_min"):
            for familia, pred in self.pred_test[target].items():
                ciclo[f"{target}_{familia}"] = pred
            ciclo[f"{target}_pred"] = ciclo[f"{target}_{self.elegidos[target]['familia']}"]
        historico = ciclo["Turno"].map(self.min_por_m3ha_train)
        ratio = ciclo[COLUMNA_CAUDAL].fillna(historico)  # caudal de los últimos 30 días
        ciclo["duracion_min_pred"] = ciclo["riego_m3ha_pred"] * ratio
        ciclo["fin_min_pred"] = ciclo["inicio_min_pred"] + ciclo["duracion_min_pred"]
        ciclo = ciclo.drop(columns=[COLUMNA_CAUDAL])

        modelo = f"{self.elegidos['riego_m3ha']['familia']} + caudal 30 días"
        self._registrar("duracion_min", modelo, "test",
                        metricas.regresion(ciclo["duracion_min_real"], ciclo["duracion_min_pred"]))
        self._registrar("duracion_min", "caudal 30 días (con m3/ha real)", "test",
                        metricas.regresion(ciclo["duracion_min_real"], ciclo["riego_m3ha_real"] * ratio))
        self._registrar("duracion_min", "caudal histórico (con m3/ha real)", "test",
                        metricas.regresion(ciclo["duracion_min_real"], ciclo["riego_m3ha_real"] * historico))
        self._registrar("fin_min", modelo, "test",
                        metricas.regresion(ciclo["fin_min_real"], ciclo["fin_min_pred"]))
        return turno.reset_index(drop=True), ciclo.reset_index(drop=True)

    def _plan(self, modelos: dict[str, Any], ciclos: pd.DataFrame, rangos=None, metadata=None) -> PlanRiego:
        return PlanRiego(
            modelos=modelos,
            features={k: v["features"] for k, v in self.elegidos.items()},
            max_ciclos=self.config.plan.max_ciclos,
            min_por_m3ha=self._min_por_m3ha(ciclos),
            area_ha=self._area(ciclos),
            rango_m3ha=(float(ciclos["riego_m3ha"].quantile(0.001)), float(ciclos["riego_m3ha"].quantile(0.999))),
            pausa_min=self.config.plan.pausa_min_entre_ciclos,
            caudal_dinamico=True,
            rangos=rangos or {},
            elegidos={k: v["familia"] for k, v in self.elegidos.items()},
            metadata=metadata or {},
        )

    def _entrenar_rangos(self, ci: pd.DataFrame, margenes: dict[str, float] | None = None) -> dict[str, Any]:
        """Modelos p10/p90 para m3/ha e inicio (ajustados con ``ci``)."""
        cfg = self.config.rangos
        if not cfg.habilitado:
            return {}
        numericas = [c for c in self.f_ciclo if c not in self.categoricas]
        rangos = {}
        for target in ("riego_m3ha", "inicio_min"):
            modelo = RangoCuantiles(self.categoricas, numericas, cfg.inferior, cfg.superior, self.config.seed)
            rangos[target] = self._ajustar(modelo, ci[self.f_ciclo], ci[target])
            rangos[target].margen_ = (margenes or {}).get(target, 0.0)
        return rangos

    def _evaluar_rangos(self, ci: pd.DataFrame) -> None:
        """Calibra el margen en validación y mide la cobertura real en test."""
        if not self.config.rangos.habilitado:
            self.rangos_train, self.margenes_rango = {}, {}
            return
        train = ci[ci["conjunto"] == "train"]
        val = ci[(ci["conjunto"] == "validacion") & self._mascara_eval(ci)]
        test = ci[(ci["conjunto"] == "test") & self._mascara_eval(ci)]
        self.rangos_train = self._entrenar_rangos(train)
        self.margenes_rango = {t: m.calcular_margen(val[self.f_ciclo], val[t]) for t, m in self.rangos_train.items()}
        esperado = self.config.rangos.superior - self.config.rangos.inferior
        for target, modelo in self.rangos_train.items():
            real = test[target].to_numpy()
            for nombre, margen in (("LightGBM cuantiles (sin calibrar)", 0.0),
                                   ("LightGBM cuantiles calibrado", self.margenes_rango[target])):
                modelo.margen_ = margen
                bajo, alto = modelo.predict(test[self.f_ciclo])
                self.filas.append({
                    "target": f"rango {target}", "modelo": nombre, "conjunto": "test",
                    "n": len(real), "cobertura": float(np.mean((real >= bajo) & (real <= alto))),
                    "cobertura_esperada": esperado, "ancho_medio": float(np.mean(alto - bajo)),
                })
                self.logger.info("  rango %-11s %-34s cobertura test=%.1f%% (esperada %.0f%%) ancho=%.1f",
                                 target, nombre, 100 * self.filas[-1]["cobertura"], 100 * esperado,
                                 self.filas[-1]["ancho_medio"])

    def _evaluar_plan(self, td, ci) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Plan completo en test: n_ciclos predicho -> ciclos -> horario."""
        modelos = {k: v["estimador_train"] for k, v in self.elegidos.items()}
        plan = self._plan(modelos, ci[ci["conjunto"] == "train"], getattr(self, "rangos_train", {}))
        test = td[(td["conjunto"] == "test") & self._mascara_eval(td)]
        entrada = test
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
        comparado = comparado.rename(columns={
            "n_ciclos": "n_ciclos_real", "riego_total_m3ha": "riego_total_m3ha_real",
            "duracion_total_min": "duracion_total_min_real", "inicio_primer_min": "inicio_primer_min_real",
            "fin_ultimo_min": "fin_ultimo_min_real",
        })
        for target in ("riego_total_m3ha", "duracion_total_min", "inicio_primer_min", "fin_ultimo_min"):
            self._registrar(f"plan: {target}", "plan completo", "test",
                            metricas.regresion(comparado[f"{target}_real"], comparado[f"{target}_pred"]))
        acierto = (comparado["n_ciclos_real"].clip(upper=self.config.plan.max_ciclos)
                   == comparado["n_ciclos_pred"]).mean()
        self.logger.info("Plan en test: acierto n_ciclos=%.3f | RMSE total m3/ha=%.2f", acierto,
                         metricas.regresion(comparado["riego_total_m3ha_real"],
                                            comparado["riego_total_m3ha_pred"])["rmse"])
        return comparado, predicho

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
            "version": self.inicio_corrida.strftime("%Y-%m-%d_%H%M"),
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
        return self._plan(modelos, ci, self._entrenar_rangos(ci, getattr(self, "margenes_rango", {})), metadata)

    # ------------------------------------------------------------------ #
    def _info_corrida(self, td, ci, ruta_modelo) -> dict[str, Any]:
        conteo = {c: int((td["conjunto"] == c).sum()) for c in ("train", "validacion", "test")}
        conteo_ci = {c: int((ci["conjunto"] == c).sum()) for c in ("train", "validacion", "test")}
        cortes = self.cortes.to_dict()
        return {
            "Fecha de la corrida": self.inicio_corrida.strftime("%Y-%m-%d %H:%M"),
            "Datos usados": f"{td['Fecha'].min():%Y-%m-%d} a {td['Fecha'].max():%Y-%m-%d}",
            "Train": f"hasta {cortes['fin_train']} · {conteo['train']} turno-días · {conteo_ci['train']} ciclos",
            "Validación": f"{cortes['inicio_validacion']} a {cortes['fin_validacion']} · "
                          f"{conteo['validacion']} turno-días · {conteo_ci['validacion']} ciclos",
            "Test": f"desde {cortes['inicio_test']} · {conteo['test']} turno-días · {conteo_ci['test']} ciclos",
            "Separación entre bloques": f"{self.config.split.gap_dias} días",
            "Días incompletos en la evaluación": "excluidos" if self.config.excluir_dias_incompletos_eval else "incluidos",
            "Features": (f"extendidas ({len(self.f_turno)} turno-día / {len(self.f_ciclo)} ciclo)"
                         if self.features_extendidas
                         else f"base ({len(self.f_turno)} turno-día / {len(self.f_ciclo)} ciclo)"),
            "Modelos comparados": " | ".join(f"{t}: {', '.join(self._candidatos(t))}" for t in DESCRIPCION_TARGET),
            "Búsqueda de hiperparámetros": "sí" if self.config.tuning.habilitado else "no (parámetros del YAML)",
            "Modelo final guardado en": str(ruta_modelo),
        }

    def _log_split(self, td, ci) -> None:
        self.logger.info("Split temporal: %s", self.cortes.to_dict())
        for conjunto in ("train", "validacion", "test", "gap"):
            self.logger.info("  %-10s turno-días=%5d ciclos=%6d", conjunto,
                             int((td["conjunto"] == conjunto).sum()), int((ci["conjunto"] == conjunto).sum()))


def entrenar(config: Config, logger) -> dict[str, Any]:
    return Entrenador(config, logger).ejecutar()
