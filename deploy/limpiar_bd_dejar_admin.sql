-- Limpieza de datos de prueba antes de salir a producción (esquema riego).
--
-- Deja:   los usuarios con rol admin, catálogos (empresa, fundo, módulo, turnos, lotes, motivos),
--         parámetros de pulsos, versiones de modelo y TODOS los datos de campo: riego histórico y
--         cargado por Excel, meteorología, Phytech, NDVI, ambiente diario e ingestas.
-- Borra:  cronogramas (versiones, turnos, ciclos, eventos), generaciones y fotos de entradas,
--         correos, auditoría, sesiones, intentos de login, recuperaciones de contraseña, los
--         usuarios que no son admin y el riego creado desde la app durante las pruebas
--         (origen 'cronograma' = provisional y 'manual' = edición manual).
--
-- Cómo correrlo: Supabase → SQL Editor → pegar todo → Run. Es una sola transacción: si algo
-- falla no cambia nada. Las protecciones (triggers) contra borrado se apagan solo dentro de la
-- transacción y se vuelven a encender al final.

BEGIN;

ALTER TABLE riego.auditoria          DISABLE TRIGGER USER;
ALTER TABLE riego.cronograma         DISABLE TRIGGER USER;
ALTER TABLE riego.cronograma_version DISABLE TRIGGER USER;
ALTER TABLE riego.cronograma_turno   DISABLE TRIGGER USER;
ALTER TABLE riego.cronograma_ciclo   DISABLE TRIGGER USER;
ALTER TABLE riego.cronograma_evento  DISABLE TRIGGER USER;
ALTER TABLE riego.prediccion_entrada DISABLE TRIGGER USER;
ALTER TABLE riego.riego_registro     DISABLE TRIGGER USER;
ALTER TABLE riego.riego_ciclo        DISABLE TRIGGER USER;

-- 1. Riego creado desde la app (provisional de cronogramas y ediciones manuales)
CREATE TEMP TABLE _riego_borrar ON COMMIT DROP AS
    SELECT id, turno_id, fecha FROM riego.riego_registro WHERE origen IN ('cronograma', 'manual');
UPDATE riego.riego_registro SET basado_en_id = NULL WHERE basado_en_id IN (SELECT id FROM _riego_borrar);
UPDATE riego.carga_riego_turno_dia SET vigente_id_comparado = NULL
    WHERE vigente_id_comparado IN (SELECT id FROM _riego_borrar);
DELETE FROM riego.riego_ciclo    WHERE registro_id IN (SELECT id FROM _riego_borrar);
DELETE FROM riego.riego_registro WHERE id IN (SELECT id FROM _riego_borrar);
-- Donde se borró la versión vigente, vuelve a ser vigente la última que quedó
UPDATE riego.riego_registro SET vigente = true
WHERE id IN (
    SELECT DISTINCT ON (r.turno_id, r.fecha) r.id
    FROM riego.riego_registro r
    JOIN (SELECT DISTINCT turno_id, fecha FROM _riego_borrar) b USING (turno_id, fecha)
    WHERE NOT EXISTS (SELECT 1 FROM riego.riego_registro v
                      WHERE v.turno_id = r.turno_id AND v.fecha = r.fecha AND v.vigente)
    ORDER BY r.turno_id, r.fecha, r.version DESC
);

-- 2. Cronogramas y todo lo que cuelga de ellos
DELETE FROM riego.notificacion_correo;
DELETE FROM riego.cronograma_evento;
DELETE FROM riego.cronograma_ciclo;
DELETE FROM riego.cronograma_turno;
UPDATE riego.cronograma SET borrador_version_id = NULL, version_publicada_id = NULL, visto_version_id = NULL;
DELETE FROM riego.cronograma_version;
DELETE FROM riego.cronograma;
DELETE FROM riego.prediccion_entrada;
DELETE FROM riego.generacion;

-- 3. Actividad de usuarios
DELETE FROM riego.auditoria;
DELETE FROM riego.sesion_refresh;
DELETE FROM riego.password_reset;
DELETE FROM riego.intento_login;

-- 4. Usuarios: solo quedan los admin (lo que hicieron otros queda sin autor, no se borra)
CREATE TEMP TABLE _usuarios_borrar ON COMMIT DROP AS
    SELECT id FROM riego.usuario WHERE rol <> 'admin';
UPDATE riego.riego_registro    SET creado_por      = NULL WHERE creado_por      IN (SELECT id FROM _usuarios_borrar);
UPDATE riego.carga_riego       SET subido_por      = NULL WHERE subido_por      IN (SELECT id FROM _usuarios_borrar);
UPDATE riego.carga_riego       SET confirmado_por  = NULL WHERE confirmado_por  IN (SELECT id FROM _usuarios_borrar);
UPDATE riego.ingesta_corrida   SET usuario_id      = NULL WHERE usuario_id      IN (SELECT id FROM _usuarios_borrar);
UPDATE riego.parametros_pulsos SET actualizado_por = NULL WHERE actualizado_por IN (SELECT id FROM _usuarios_borrar);
DELETE FROM riego.usuario WHERE id IN (SELECT id FROM _usuarios_borrar);

ALTER TABLE riego.auditoria          ENABLE TRIGGER USER;
ALTER TABLE riego.cronograma         ENABLE TRIGGER USER;
ALTER TABLE riego.cronograma_version ENABLE TRIGGER USER;
ALTER TABLE riego.cronograma_turno   ENABLE TRIGGER USER;
ALTER TABLE riego.cronograma_ciclo   ENABLE TRIGGER USER;
ALTER TABLE riego.cronograma_evento  ENABLE TRIGGER USER;
ALTER TABLE riego.prediccion_entrada ENABLE TRIGGER USER;
ALTER TABLE riego.riego_registro     ENABLE TRIGGER USER;
ALTER TABLE riego.riego_ciclo        ENABLE TRIGGER USER;

-- Resultado (debe mostrar solo admins y 0 cronogramas)
SELECT 'usuarios admin' AS que, count(*) FROM riego.usuario
UNION ALL SELECT 'usuarios no admin', count(*) FROM riego.usuario WHERE rol <> 'admin'
UNION ALL SELECT 'cronogramas', count(*) FROM riego.cronograma
UNION ALL SELECT 'turno-días de riego vigentes', count(*) FROM riego.riego_registro WHERE vigente
UNION ALL SELECT 'turno-días sin versión vigente',
    count(*) FROM (SELECT turno_id, fecha FROM riego.riego_registro GROUP BY 1, 2 HAVING NOT bool_or(vigente)) x;

COMMIT;
