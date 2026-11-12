"""Enums de Postgres (esquema ``riego``) y sus equivalentes en Python.

Los valores se guardan tal cual (minúsculas). Agregar un valor exige una migración
(``ALTER TYPE riego.<tipo> ADD VALUE ...``).
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum

from app.db.base import ESQUEMA


class RolUsuario(str, enum.Enum):
    admin = "admin"
    encargado = "encargado"
    programador = "programador"
    subgerente = "subgerente"


class TipoIntento(str, enum.Enum):
    login = "login"
    recuperar = "recuperar"
    restablecer = "restablecer"
    cambiar_password = "cambiar_password"  # migración 0003


class EstadoCorreo(str, enum.Enum):
    pendiente = "pendiente"
    enviando = "enviando"
    enviado = "enviado"
    error = "error"
    sin_destinatarios = "sin_destinatarios"


class DisparoIngesta(str, enum.Enum):
    programado = "programado"
    manual = "manual"
    script = "script"


class EstadoIngesta(str, enum.Enum):
    en_curso = "en_curso"
    ok = "ok"
    parcial = "parcial"
    error = "error"


class OrigenMeteo(str, enum.Enum):
    excel_historico = "excel_historico"
    weatherlink = "weatherlink"


class EstadoRiego(str, enum.Enum):
    provisional = "provisional"
    aplicado = "aplicado"


class OrigenRiego(str, enum.Enum):
    historico = "historico"
    cronograma = "cronograma"
    excel = "excel"
    manual = "manual"
    controlador = "controlador"


class EstadoCarga(str, enum.Enum):
    previsualizada = "previsualizada"
    confirmada = "confirmada"
    descartada = "descartada"
    vencida = "vencida"


class ResultadoCarga(str, enum.Enum):
    nuevo = "nuevo"
    igual = "igual"
    reemplaza_provisional = "reemplaza_provisional"
    reemplaza_aplicado = "reemplaza_aplicado"
    sin_riego = "sin_riego"
    error = "error"


class TipoGeneracion(str, enum.Enum):
    generar = "generar"
    regenerar = "regenerar"


class EstadoCronograma(str, enum.Enum):
    borrador = "borrador"
    publicado = "publicado"
    visto = "visto"
    correccion_solicitada = "correccion_solicitada"


class OrigenVersion(str, enum.Enum):
    modelo = "modelo"
    regenerado = "regenerado"
    correccion = "correccion"
    edicion = "edicion"


class OrigenRiegoD1(str, enum.Enum):
    aplicado = "aplicado"
    provisional = "provisional"
    cronograma = "cronograma"
    ninguno = "ninguno"


class TipoEventoCronograma(str, enum.Enum):
    anulado = "anulado"
    generado = "generado"
    regenerado = "regenerado"
    corregido = "corregido"
    borrador_descartado = "borrador_descartado"
    publicado = "publicado"
    modificado = "modificado"
    visto_programador = "visto_programador"
    abierto_programador = "abierto_programador"
    visto_subgerente = "visto_subgerente"
    correccion_solicitada = "correccion_solicitada"
    correccion_atendida = "correccion_atendida"
    correccion_mantenida = "correccion_mantenida"
    riego_provisional_creado = "riego_provisional_creado"
    riego_provisional_actualizado = "riego_provisional_actualizado"
    riego_reemplazado_excel = "riego_reemplazado_excel"
    riego_marcado_aplicado = "riego_marcado_aplicado"
    exportado = "exportado"


def pg_enum(enum_cls: type[enum.Enum], nombre: str) -> SAEnum:
    """Tipo enum de Postgres en el esquema ``riego`` que guarda los valores (no los nombres)."""
    return SAEnum(
        enum_cls,
        name=nombre,
        schema=ESQUEMA,
        values_callable=lambda cls: [m.value for m in cls],
        validate_strings=True,
        create_type=False,  # los crea la migración 0001
    )


# Nombre del tipo en Postgres -> enum de Python (lo usa la migración y los tests).
TIPOS_ENUM: dict[str, type[enum.Enum]] = {
    "rol_usuario": RolUsuario,
    "tipo_intento": TipoIntento,
    "estado_correo": EstadoCorreo,
    "disparo_ingesta": DisparoIngesta,
    "estado_ingesta": EstadoIngesta,
    "origen_meteo": OrigenMeteo,
    "estado_riego": EstadoRiego,
    "origen_riego": OrigenRiego,
    "estado_carga": EstadoCarga,
    "resultado_carga": ResultadoCarga,
    "tipo_generacion": TipoGeneracion,
    "estado_cronograma": EstadoCronograma,
    "origen_version": OrigenVersion,
    "origen_riego_d1": OrigenRiegoD1,
    "tipo_evento_cronograma": TipoEventoCronograma,
}

ROL_USUARIO = pg_enum(RolUsuario, "rol_usuario")
TIPO_INTENTO = pg_enum(TipoIntento, "tipo_intento")
ESTADO_CORREO = pg_enum(EstadoCorreo, "estado_correo")
DISPARO_INGESTA = pg_enum(DisparoIngesta, "disparo_ingesta")
ESTADO_INGESTA = pg_enum(EstadoIngesta, "estado_ingesta")
ORIGEN_METEO = pg_enum(OrigenMeteo, "origen_meteo")
ESTADO_RIEGO = pg_enum(EstadoRiego, "estado_riego")
ORIGEN_RIEGO = pg_enum(OrigenRiego, "origen_riego")
ESTADO_CARGA = pg_enum(EstadoCarga, "estado_carga")
RESULTADO_CARGA = pg_enum(ResultadoCarga, "resultado_carga")
TIPO_GENERACION = pg_enum(TipoGeneracion, "tipo_generacion")
ESTADO_CRONOGRAMA = pg_enum(EstadoCronograma, "estado_cronograma")
ORIGEN_VERSION = pg_enum(OrigenVersion, "origen_version")
ORIGEN_RIEGO_D1 = pg_enum(OrigenRiegoD1, "origen_riego_d1")
TIPO_EVENTO_CRONOGRAMA = pg_enum(TipoEventoCronograma, "tipo_evento_cronograma")
