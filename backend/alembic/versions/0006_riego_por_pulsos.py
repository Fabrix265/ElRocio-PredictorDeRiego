"""Riego por pulsos: parámetros por módulo, resumen del cálculo y plan original del modelo.

- ``parametros_pulsos``: los datos fijos de la planilla «MODELO RIEGO POR PULSOS – PALTO»
  (suelo, sistema, fenología, curvas por hora). CRUD para riego_app, RLS y ``updated_at`` por
  trigger. Se siembra una fila por módulo existente con los valores de la planilla.
- ``cronograma_version.calculo_pulsos``: resumen del cálculo de la versión (curva, bloques, pulsos).
- ``prediccion_entrada.plan_modelo``: los ciclos que predijo el modelo, para que el historial del
  día siguiente use la predicción del modelo y no los pulsos.
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.migraciones import preparar_tabla

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMA = "riego"

# Valores de la planilla (hoja «PULSOS PALTO», noviembre 2026), congelados en esta migración.
CURVAS = {
    "1": {"6": 2, "7": 3, "8": 5, "9": 9, "10": 13, "11": 13, "12": 13, "13": 13, "14": 12, "15": 9,
          "16": 5, "17": 3},
    "2": {"6": 6, "7": 8, "8": 9, "9": 9, "10": 9, "11": 9, "12": 9, "13": 9, "14": 9, "15": 9,
          "16": 8, "17": 6},
    "3": {"3": 4, "4": 5, "5": 5, **{str(h): 6 for h in range(6, 18)}, "18": 5, "19": 5, "20": 4},
}
AGOTAMIENTO_POR_FASE = {"Vegetativo": 0.10, "Floración": 0.05, "Cuajado": 0.05,
                        "Crecimiento de fruta": 0.05, "Maduración": 0.10, "Cosecha": 0.10}


def upgrade() -> None:
    op.create_table(
        "parametros_pulsos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("modulo_id", sa.BigInteger(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("textura_suelo", sa.String(length=30), nullable=False),
        sa.Column("capacidad_campo", sa.Double(), nullable=False),
        sa.Column("punto_marchitez", sa.Double(), nullable=False),
        sa.Column("agotamiento_maximo", sa.Double(), nullable=False),
        sa.Column("infiltracion_basica_mmh", sa.Double(), nullable=False),
        sa.Column("ancho_humedo_m", sa.Double(), nullable=False),
        sa.Column("profundidad_raices_m", sa.Double(), nullable=False),
        sa.Column("diametro_bulbo_m", sa.Double(), nullable=True),
        sa.Column("distancia_hileras_m", sa.Double(), nullable=False),
        sa.Column("distancia_plantas_m", sa.Double(), nullable=False),
        sa.Column("mangueras_por_hilera", sa.SmallInteger(), nullable=False),
        sa.Column("separacion_mangueras_m", sa.Double(), nullable=False),
        sa.Column("distancia_goteros_m", sa.Double(), nullable=False),
        sa.Column("caudal_gotero_lh", sa.Double(), nullable=False),
        sa.Column("reposo_min_por_hora", sa.Double(), nullable=False),
        sa.Column("eficiencia_aplicacion", sa.Double(), nullable=False),
        sa.Column("fase_fenologica", sa.String(length=40), nullable=False),
        sa.Column("agotamiento_por_fase", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agotamiento_automatico", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("umbral_etr_1", sa.Double(), nullable=False),
        sa.Column("umbral_etr_2", sa.Double(), nullable=False),
        sa.Column("modo_ventana", sa.String(length=30), nullable=False),
        sa.Column("curvas", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ajustar_pulso_al_total", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("actualizado_por", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["modulo_id"], ["riego.modulo.id"], name=op.f("fk_parametros_pulsos_modulo_id_modulo")),
        sa.ForeignKeyConstraint(["actualizado_por"], ["riego.usuario.id"],
                                name=op.f("fk_parametros_pulsos_actualizado_por_usuario")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parametros_pulsos")),
        sa.UniqueConstraint("modulo_id", name=op.f("uq_parametros_pulsos_modulo_id")),
        schema=ESQUEMA,
    )
    op.create_index(op.f("ix_parametros_pulsos_actualizado_por"), "parametros_pulsos", ["actualizado_por"],
                    unique=False, schema=ESQUEMA)
    preparar_tabla("parametros_pulsos", modo="crud")
    op.execute(f"CREATE TRIGGER tg_parametros_pulsos_updated_at BEFORE UPDATE ON {ESQUEMA}.parametros_pulsos "
               f"FOR EACH ROW EXECUTE FUNCTION {ESQUEMA}.fijar_updated_at()")
    op.execute(sa.text(f"""
        INSERT INTO {ESQUEMA}.parametros_pulsos (
            modulo_id, activo, textura_suelo, capacidad_campo, punto_marchitez, agotamiento_maximo,
            infiltracion_basica_mmh, ancho_humedo_m, profundidad_raices_m, diametro_bulbo_m,
            distancia_hileras_m, distancia_plantas_m, mangueras_por_hilera, separacion_mangueras_m,
            distancia_goteros_m, caudal_gotero_lh, reposo_min_por_hora, eficiencia_aplicacion,
            fase_fenologica, agotamiento_por_fase, agotamiento_automatico, umbral_etr_1, umbral_etr_2,
            modo_ventana, curvas, ajustar_pulso_al_total)
        SELECT id, true, 'Arenoso', 0.14, 0.04, 0.25, 40, 2, 0.5, NULL, 6, 2, 4, 0.5, 0.5, 1.6, 5, 0.85,
               'Crecimiento de fruta', CAST(:fases AS jsonb), true, 2.5, 5.0,
               'automatico_con_respaldo', CAST(:curvas AS jsonb), true
        FROM {ESQUEMA}.modulo
    """).bindparams(fases=json.dumps(AGOTAMIENTO_POR_FASE, ensure_ascii=False), curvas=json.dumps(CURVAS)))

    op.add_column("cronograma_version", sa.Column("calculo_pulsos", postgresql.JSONB(astext_type=sa.Text()),
                                                  nullable=True), schema=ESQUEMA)
    op.add_column("prediccion_entrada", sa.Column("plan_modelo", postgresql.JSONB(astext_type=sa.Text()),
                                                  nullable=True), schema=ESQUEMA)


def downgrade() -> None:
    op.drop_column("prediccion_entrada", "plan_modelo", schema=ESQUEMA)
    op.drop_column("cronograma_version", "calculo_pulsos", schema=ESQUEMA)
    op.drop_index(op.f("ix_parametros_pulsos_actualizado_por"), table_name="parametros_pulsos", schema=ESQUEMA)
    op.drop_table("parametros_pulsos", schema=ESQUEMA)
