"""Recuperación por correo (cola + worker), restablecimiento, cambio de contraseña y primer ingreso."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.core.tiempo import ahora_utc
from app.emails.smtp import ArchivoMailer
from app.models import Auditoria, NotificacionCorreo, PasswordReset, SesionRefresh
from app.models.enums import EstadoCorreo
from app.services import correo_service
from tests.conftest import API, PASSWORD_PRUEBA, MailerQueFalla, bearer, login, token_de

MENSAJE_RECUPERAR = "Si el usuario existe, enviaremos un enlace a su correo."
NUEVA = "OtraClave2026x"


def _token_del_correo(texto: str) -> str:
    coincidencia = re.search(r"/restablecer#token=([A-Za-z0-9_-]+)", texto)
    assert coincidencia, "el correo no trae el enlace de restablecimiento"
    return coincidencia.group(1)


def _pedir_y_enviar(client: TestClient, db: Session, mailer, identificador: str) -> str:
    respuesta = client.post(f"{API}/auth/recuperar", json={"identificador": identificador})
    assert respuesta.status_code == 202
    assert respuesta.json() == {"detail": MENSAJE_RECUPERAR}
    resultado = correo_service.procesar_pendientes(db, mailer)
    assert resultado.enviados == 1
    return _token_del_correo(mailer.texto())


def test_recuperar_worker_restablecer_un_solo_uso(client: TestClient, crear_usuario, db: Session, mailer):
    crear_usuario("nora", correo="nora@example.com")
    access_viejo = token_de(client, "nora")
    rt_viejo = client.cookies["rt"]

    respuesta = client.post(f"{API}/auth/recuperar", json={"identificador": "NORA@example.com"})
    assert respuesta.status_code == 202
    # La cola guarda solo el usuario: ni token ni enlace.
    notificacion = db.scalars(select(NotificacionCorreo)).one()
    assert notificacion.estado == EstadoCorreo.pendiente
    assert notificacion.usuario_id is not None
    assert "token" not in str(notificacion.contexto)
    assert db.scalar(select(func.count()).select_from(PasswordReset)) == 0

    assert correo_service.procesar_pendientes(db, mailer).enviados == 1
    db.refresh(notificacion)
    assert notificacion.estado == EstadoCorreo.enviado
    assert notificacion.destinatarios == ["nora@example.com"]
    mensaje = mailer.enviados[0]
    assert mensaje["To"] == "nora@example.com"
    html = mailer.html()
    assert "Grupo El Rocío" in html and "#2A7042" in html and "Restablecer contraseña" in html
    token = _token_del_correo(mailer.texto())
    assert f"http://localhost:5173/restablecer#token={token}" in html
    # En la BD solo el SHA-256 del token, con vencimiento a los 30 minutos.
    reset = db.scalars(select(PasswordReset)).one()
    assert reset.token_hash == hash_token(token)
    assert timedelta(minutes=29) < reset.expira_at - ahora_utc() <= timedelta(minutes=30)

    debil = client.post(f"{API}/auth/restablecer", json={"token": token, "password": "corta1"})
    assert debil.status_code == 422
    assert "al menos 10 caracteres" in debil.json()["detail"]

    ok = client.post(f"{API}/auth/restablecer", json={"token": token, "password": NUEVA})
    assert ok.status_code == 204
    otra_vez = client.post(f"{API}/auth/restablecer", json={"token": token, "password": NUEVA + "b"})
    assert otra_vez.status_code == 400
    assert otra_vez.json() == {"detail": "El enlace no es válido o ya venció."}

    # La contraseña cambió, los accesos anteriores quedaron invalidados.
    assert login(client, "nora", PASSWORD_PRUEBA).status_code == 401
    assert client.get(f"{API}/auth/me", headers=bearer(access_viejo)).status_code == 401
    assert db.scalars(select(SesionRefresh).where(SesionRefresh.token_hash == hash_token(rt_viejo))).one().revocado_at
    assert login(client, "nora", NUEVA).status_code == 200
    acciones = set(db.scalars(select(Auditoria.accion).where(Auditoria.username == "nora")))
    assert "password_restablecido" in acciones
    # La solicitud es anónima: queda sin actor, con el usuario solo en entidad_id.
    solicitud = db.scalars(select(Auditoria).where(Auditoria.accion == "recuperar_solicitado")).one()
    assert (solicitud.usuario_id, solicitud.username, solicitud.rol) == (None, None, None)
    assert solicitud.entidad_id == str(notificacion.usuario_id)


def test_enlace_vencido(client: TestClient, crear_usuario, db: Session, mailer):
    crear_usuario("olga")
    token = _pedir_y_enviar(client, db, mailer, "olga")
    with time_machine.travel(ahora_utc() + timedelta(minutes=31)):
        respuesta = client.post(f"{API}/auth/restablecer", json={"token": token, "password": NUEVA})
    assert respuesta.status_code == 400
    assert respuesta.json()["detail"] == "El enlace no es válido o ya venció."


def test_nuevo_enlace_invalida_el_anterior(client: TestClient, crear_usuario, db: Session, mailer):
    crear_usuario("pia")
    primero = _pedir_y_enviar(client, db, mailer, "pia")
    segundo = _pedir_y_enviar(client, db, mailer, "pia")
    assert client.post(f"{API}/auth/restablecer", json={"token": primero, "password": NUEVA}).status_code == 400
    assert client.post(f"{API}/auth/restablecer", json={"token": segundo, "password": NUEVA}).status_code == 204


def test_recuperar_no_revela_si_el_usuario_existe(client: TestClient, crear_usuario, db: Session, mailer):
    crear_usuario("quique", activo=False)
    for identificador in ("no_existe", "nadie@example.com", "quique"):
        respuesta = client.post(f"{API}/auth/recuperar", json={"identificador": identificador})
        assert respuesta.status_code == 202
        assert respuesta.json() == {"detail": MENSAJE_RECUPERAR}
    assert db.scalar(select(func.count()).select_from(NotificacionCorreo)) == 0
    assert correo_service.procesar_pendientes(db, mailer).total == 0


def test_limite_de_recuperar_por_usuario(client: TestClient, crear_usuario):
    crear_usuario("rosa")
    for _ in range(3):
        assert client.post(f"{API}/auth/recuperar", json={"identificador": "rosa"}).status_code == 202
    respuesta = client.post(f"{API}/auth/recuperar", json={"identificador": "rosa"})
    assert respuesta.status_code == 429
    assert respuesta.json()["detail"].startswith("Demasiados intentos.")


def test_limite_de_restablecer_por_ip(client: TestClient):
    for i in range(10):
        respuesta = client.post(f"{API}/auth/restablecer", json={"token": f"falso{i}", "password": NUEVA})
        assert respuesta.status_code == 400
    assert client.post(f"{API}/auth/restablecer", json={"token": "x", "password": NUEVA}).status_code == 429


# --- Cola de correos ----------------------------------------------------------

def test_reintentos_con_espera_creciente_y_error_al_quinto(client: TestClient, crear_usuario, db: Session):
    crear_usuario("sara")
    client.post(f"{API}/auth/recuperar", json={"identificador": "sara"})
    falla = MailerQueFalla()
    esperas = []
    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        for intento in range(1, 6):
            resultado = correo_service.procesar_pendientes(db, falla)
            notificacion = db.scalars(select(NotificacionCorreo)).one()
            db.refresh(notificacion)
            assert notificacion.intentos == intento
            assert "no-debe-verse" not in notificacion.ultimo_error
            if intento < 5:
                assert resultado.reintentos == 1
                assert notificacion.estado == EstadoCorreo.pendiente
                esperas.append(notificacion.proximo_intento_at - ahora_utc())
                # Antes de la espera no se vuelve a intentar.
                assert correo_service.procesar_pendientes(db, falla).total == 0
                reloj.shift(esperas[-1] + timedelta(seconds=1))
            else:
                assert resultado.errores == 1
                assert notificacion.estado == EstadoCorreo.error
    assert esperas == sorted(esperas) and len(set(esperas)) == 4
    assert falla.intentos == 5
    # Un envío fallido no deja tokens de recuperación válidos.
    assert db.scalar(select(func.count()).select_from(PasswordReset)) == 0


def test_correo_enviando_abandonado_se_retoma(client: TestClient, crear_usuario, db: Session, mailer):
    crear_usuario("tito")
    client.post(f"{API}/auth/recuperar", json={"identificador": "tito"})
    assert correo_service.reclamar(db)  # un proceso lo tomó y murió
    assert correo_service.procesar_pendientes(db, mailer).total == 0
    with time_machine.travel(ahora_utc() + timedelta(minutes=6)):
        assert correo_service.procesar_pendientes(db, mailer).enviados == 1


def test_correo_por_rol_sin_destinatarios(db: Session, mailer):
    from app.models.enums import RolUsuario

    correo_service.encolar(db, tipo="publicado", asunto="Cronograma publicado",
                           rol_destino=RolUsuario.subgerente)
    db.commit()
    assert correo_service.procesar_pendientes(db, mailer).sin_destinatarios == 1
    assert db.scalars(select(NotificacionCorreo)).one().estado == EstadoCorreo.sin_destinatarios


def test_modo_archivo_guarda_eml_sin_loguear_el_enlace(
    client: TestClient, crear_usuario, db: Session, tmp_path, caplog
):
    crear_usuario("ugo")
    client.post(f"{API}/auth/recuperar", json={"identificador": "ugo"})
    with caplog.at_level(logging.INFO):
        assert correo_service.procesar_pendientes(db, ArchivoMailer(tmp_path)).enviados == 1
    archivos = list(tmp_path.glob("*.eml"))
    assert len(archivos) == 1
    assert "restablecer#token=" in archivos[0].read_bytes().decode("utf-8", "replace").replace("=\n", "")
    assert "correo guardado en archivo" in caplog.text
    assert "token" not in caplog.text and "restablecer" not in caplog.text


# --- Cambio de contraseña y primer ingreso ------------------------------------

def test_debe_cambiar_password_bloquea_hasta_cambiarla(client: TestClient, crear_usuario, db: Session):
    crear_usuario("vale", rol="admin", debe_cambiar_password=True)
    respuesta = login(client, "vale")
    assert respuesta.status_code == 200
    assert respuesta.json()["usuario"]["debe_cambiar_password"] is True
    token = respuesta.json()["access_token"]

    for ruta in ("/fundos", "/usuarios", "/auditoria", "/motivos-correccion"):
        bloqueado = client.get(f"{API}{ruta}", headers=bearer(token))
        assert bloqueado.status_code == 403
        assert bloqueado.json() == {"detail": "Debes cambiar tu contraseña"}
    assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 200

    def cambiar(actual: str, nueva: str):
        return client.post(f"{API}/auth/cambiar-password", headers=bearer(token),
                           json={"password_actual": actual, "password_nueva": nueva})

    mal = cambiar("incorrecta-123", NUEVA)
    assert mal.status_code == 400
    assert mal.json() == {"detail": "La contraseña actual no es correcta."}
    assert cambiar(PASSWORD_PRUEBA, "solo-letras-aqui").status_code == 422
    assert cambiar(PASSWORD_PRUEBA, "vale").status_code == 422
    igual = cambiar(PASSWORD_PRUEBA, "Vale").json()["detail"]
    assert "igual al nombre de usuario" in igual

    ok = cambiar(PASSWORD_PRUEBA, NUEVA)
    assert ok.status_code == 200, ok.text
    cuerpo = ok.json()
    assert cuerpo["usuario"]["debe_cambiar_password"] is False
    assert "rt=" in ok.headers["set-cookie"]
    # El token anterior ya no sirve; el nuevo entra a todo.
    assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 401
    assert client.get(f"{API}/fundos", headers=bearer(cuerpo["access_token"])).status_code == 200
    assert login(client, "vale", NUEVA).status_code == 200
    assert "password_cambiado" in set(db.scalars(select(Auditoria.accion)))


def test_logout_disponible_con_debe_cambiar_password(client: TestClient, crear_usuario):
    crear_usuario("wen", debe_cambiar_password=True)
    login(client, "wen")
    respuesta = client.post(f"{API}/auth/logout", headers={"X-Requested-With": "fetch"})
    assert respuesta.status_code == 204


# --- Límite del cambio de contraseña y enlaces pendientes ---------------------

def test_cambiar_password_limita_intentos_y_cierra_accesos(
    client: TestClient, crear_usuario, db: Session
):
    crear_usuario("yoli")
    token = token_de(client, "yoli")

    def cambiar(token: str, actual: str):
        return client.post(f"{API}/auth/cambiar-password", headers=bearer(token),
                           json={"password_actual": actual, "password_nueva": NUEVA})

    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        for _ in range(5):
            respuesta = cambiar(token, "incorrecta-123")
            assert respuesta.status_code == 400
        fallos = list(db.scalars(
            select(Auditoria).where(Auditoria.accion == "password_cambio_fallido")
        ))
        assert len(fallos) == 5 and all(f.username == "yoli" for f in fallos)
        # Al quinto fallo se cierran los accesos (podría ser un access token robado).
        assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 401

        # El dueño vuelve a entrar con su contraseña, pero el límite sigue 15 minutos.
        nuevo = token_de(client, "yoli")
        bloqueado = cambiar(nuevo, PASSWORD_PRUEBA)
        assert bloqueado.status_code == 429
        assert bloqueado.json()["detail"] == "Demasiados intentos. Vuelve a intentarlo en 15 minutos."
        assert client.get(f"{API}/auth/me", headers=bearer(nuevo)).status_code == 200

        reloj.shift(timedelta(minutes=15, seconds=1))
        assert cambiar(nuevo, PASSWORD_PRUEBA).status_code == 200


def test_cambiar_password_correcta_reinicia_el_contador(client: TestClient, crear_usuario):
    crear_usuario("yoli2")
    token = token_de(client, "yoli2")
    for _ in range(4):
        respuesta = client.post(f"{API}/auth/cambiar-password", headers=bearer(token),
                                json={"password_actual": "incorrecta-1", "password_nueva": NUEVA})
        assert respuesta.status_code == 400
    # Contraseña actual correcta (aunque la nueva no cumpla la política): reinicia el contador.
    debil = client.post(f"{API}/auth/cambiar-password", headers=bearer(token),
                        json={"password_actual": PASSWORD_PRUEBA, "password_nueva": "corta"})
    assert debil.status_code == 422
    for _ in range(4):
        respuesta = client.post(f"{API}/auth/cambiar-password", headers=bearer(token),
                                json={"password_actual": "incorrecta-1", "password_nueva": NUEVA})
        assert respuesta.status_code == 400
    assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 200


def test_password_temporal_invalida_enlaces_pendientes(
    client: TestClient, crear_usuario, auth, db: Session, mailer
):
    admin = auth("admin", username="jefa_reset")
    usuario = crear_usuario("zoe")
    token = _pedir_y_enviar(client, db, mailer, "zoe")
    respuesta = client.post(f"{API}/usuarios/{usuario.id}/password-temporal", headers=admin,
                            json={"password_temporal": "Temporal2026x"})
    assert respuesta.status_code == 200, respuesta.text
    restablecer = client.post(f"{API}/auth/restablecer", json={"token": token, "password": NUEVA})
    assert restablecer.status_code == 400


def test_cambio_de_correo_invalida_enlaces_pendientes(
    client: TestClient, crear_usuario, auth, db: Session, mailer
):
    admin = auth("admin", username="jefa_correo")
    usuario = crear_usuario("zoe2")
    token = _pedir_y_enviar(client, db, mailer, "zoe2")
    respuesta = client.patch(f"{API}/usuarios/{usuario.id}", headers=admin,
                             json={"correo": "zoe2.nuevo@example.com"})
    assert respuesta.status_code == 200, respuesta.text
    restablecer = client.post(f"{API}/auth/restablecer", json={"token": token, "password": NUEVA})
    assert restablecer.status_code == 400


def test_cambiar_password_invalida_enlaces_pendientes(
    client: TestClient, crear_usuario, db: Session, mailer
):
    crear_usuario("zoe3")
    acceso = token_de(client, "zoe3")
    token = _pedir_y_enviar(client, db, mailer, "zoe3")
    cambio = client.post(f"{API}/auth/cambiar-password", headers=bearer(acceso),
                         json={"password_actual": PASSWORD_PRUEBA, "password_nueva": NUEVA})
    assert cambio.status_code == 200
    restablecer = client.post(f"{API}/auth/restablecer",
                              json={"token": token, "password": NUEVA + "z"})
    assert restablecer.status_code == 400


def test_limpieza_de_sesiones_y_enlaces_vencidos(client: TestClient, crear_usuario, db: Session, mailer):
    from app.services import auth_service

    crear_usuario("zoe4")
    login(client, "zoe4")
    _pedir_y_enviar(client, db, mailer, "zoe4")
    assert auth_service.limpiar_vencidos(db) == (0, 0)  # aún vigentes
    with time_machine.travel(ahora_utc() + timedelta(days=38)):
        assert auth_service.limpiar_vencidos(db) == (1, 1)
    assert db.scalar(select(func.count()).select_from(SesionRefresh)) == 0
    assert db.scalar(select(func.count()).select_from(PasswordReset)) == 0
