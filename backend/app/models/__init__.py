"""Modelos SQLAlchemy del esquema ``riego`` (importarlos registra todas las tablas en Base.metadata)."""

from app.models.cronograma import (
    Cronograma,
    CronogramaCiclo,
    CronogramaEvento,
    CronogramaTurno,
    CronogramaVersion,
    Generacion,
    ModeloVersion,
    MotivoCorreccion,
    PrediccionEntrada,
)
from app.models.datos import (
    AmbienteDiario,
    IngestaCorrida,
    IngestaCrudo,
    MeteoLectura,
    NdviImagen,
    PhytechPlantaDiario,
    PhytechSueloHorario,
    PronosticoClima,
)
from app.models.organizacion import Empresa, Fundo, Lote, Modulo, Turno
from app.models.pulsos import ParametrosPulsos
from app.models.riego import CargaRiego, CargaRiegoTurnoDia, RiegoCiclo, RiegoRegistro
from app.models.seguridad import (
    Auditoria,
    IntentoLogin,
    NotificacionCorreo,
    PasswordReset,
    SesionRefresh,
    Usuario,
)

__all__ = [
    "AmbienteDiario",
    "Auditoria",
    "CargaRiego",
    "CargaRiegoTurnoDia",
    "Cronograma",
    "CronogramaCiclo",
    "CronogramaEvento",
    "CronogramaTurno",
    "CronogramaVersion",
    "Empresa",
    "Fundo",
    "Generacion",
    "IngestaCorrida",
    "IngestaCrudo",
    "IntentoLogin",
    "Lote",
    "MeteoLectura",
    "ModeloVersion",
    "Modulo",
    "MotivoCorreccion",
    "NdviImagen",
    "NotificacionCorreo",
    "ParametrosPulsos",
    "PasswordReset",
    "PhytechPlantaDiario",
    "PhytechSueloHorario",
    "PrediccionEntrada",
    "PronosticoClima",
    "RiegoCiclo",
    "RiegoRegistro",
    "SesionRefresh",
    "Turno",
    "Usuario",
]
