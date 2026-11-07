"""Login, límites de intentos, enumeración, refresh rotativo, logout y tokens de acceso."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import CredencialesInvalidas, LimiteExcedido
from app.core.security import ALGORITMO_JWT, crear_access_token
from app.core.tiempo import ahora_utc
from app.models import Auditoria, SesionRefresh
from app.services import auth_service
from app.services.contexto import ContextoPeticion
from tests.conftest import API, CABECERA_FETCH, PASSWORD_PRUEBA, bearer, login, token_de

MENSAJE_CREDENCIALES = "Usuario o contraseña incorrectos"


def _refresh(client: TestClient, rt: str | None, headers: dict | None = None):
    """POST /auth/refresh enviando solo la cookie indicada (sin la del jar del cliente)."""
    client.cookies.clear()
    cabeceras = dict(CABECERA_FETCH if headers is None else headers)
    if rt is not None:
        cabeceras["Cookie"] = f"rt={rt}"
    return client.post(f"{API}/auth/refresh", headers=cabeceras)


# --- Login --------------------------------------------------------------------

def test_login_ok_devuelve_token_usuario_y_cookie(client: TestClient, crear_usuario, db: Session):
    crear_usuario("ana", rol="encargado")
    respuesta = login(client, "ANA ")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    assert cuerpo["expires_in"] == settings.access_token_minutes * 60
    assert set(cuerpo["usuario"]) == {
        "id", "username", "nombre", "correo", "rol", "activo", "debe_cambiar_password",
        "ultimo_acceso_at",
    }
    assert cuerpo["usuario"]["rol"] == "encargado"
    assert cuerpo["usuario"]["ultimo_acceso_at"] is not None

    cookie = respuesta.headers["set-cookie"]
    assert cookie.startswith("rt=")
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "SameSite=strict" in cookie
    assert f"Max-Age={7 * 24 * 3600}" in cookie
    # En la BD solo queda el hash del refresh.
    rt = respuesta.cookies["rt"]
    assert db.scalar(
        select(func.count()).select_from(SesionRefresh).where(SesionRefresh.token_hash == rt)
    ) == 0

    me = client.get(f"{API}/auth/me", headers=bearer(cuerpo["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "ana"
    acciones = list(db.scalars(select(Auditoria.accion).where(Auditoria.username == "ana")))
    assert acciones == ["login"]


def test_login_incorrecto_y_enumeracion(client: TestClient, crear_usuario, db: Session):
    crear_usuario("beto")
    crear_usuario("inactivo", activo=False)
    casos = [
        ("beto", "otra-clave-123"),  # contraseña incorrecta
        ("no_existe", PASSWORD_PRUEBA),  # usuario inexistente
        ("inactivo", PASSWORD_PRUEBA),  # usuario inactivo con la contraseña correcta
    ]
    for username, password in casos:
        respuesta = login(client, username, password)
        assert respuesta.status_code == 401
        assert respuesta.json() == {"detail": MENSAJE_CREDENCIALES}
        assert "set-cookie" not in respuesta.headers
    motivos = {
        a.username: a.detalle["motivo"]
        for a in db.scalars(select(Auditoria).where(Auditoria.accion == "login_fallido"))
    }
    assert motivos == {
        "beto": "password_incorrecta",
        "no_existe": "usuario_inexistente",
        "inactivo": "usuario_inactivo",
    }


def test_bloqueo_429_tras_5_fallos_y_vuelve_a_los_15_minutos(client: TestClient, crear_usuario):
    crear_usuario("carla")
    with time_machine.travel(ahora_utc(), tick=True) as reloj:
        for _ in range(5):
            assert login(client, "carla", "incorrecta-123").status_code == 401
        bloqueado = login(client, "carla")  # ni con la contraseña correcta
        assert bloqueado.status_code == 429
        assert bloqueado.json()["detail"] == "Demasiados intentos. Vuelve a intentarlo en 15 minutos."
        assert int(bloqueado.headers["retry-after"]) > 14 * 60
        reloj.shift(timedelta(minutes=10))
        assert login(client, "carla").json()["detail"].endswith("en 5 minutos.")
        reloj.shift(timedelta(minutes=5, seconds=1))
        assert login(client, "carla").status_code == 200


def test_limite_por_usuario_desde_varias_ip(db: Session, crear_usuario):
    crear_usuario("dora")
    for i in range(10):
        with pytest.raises(CredencialesInvalidas):
            auth_service.login(db, "dora", "incorrecta-123", ContextoPeticion(ip=f"10.0.0.{i}"))
    with pytest.raises(LimiteExcedido):
        auth_service.login(db, "dora", PASSWORD_PRUEBA, ContextoPeticion(ip="10.0.0.99"))


def test_limite_por_ip_con_varios_usuarios(db: Session):
    for i in range(30):
        with pytest.raises(CredencialesInvalidas):
            auth_service.login(db, f"fantasma{i}", "x", ContextoPeticion(ip="10.9.9.9"))
    with pytest.raises(LimiteExcedido):
        auth_service.login(db, "otro", "x", ContextoPeticion(ip="10.9.9.9"))
    # Desde otra IP sigue respondiendo normalmente.
    with pytest.raises(CredencialesInvalidas):
        auth_service.login(db, "otro", "x", ContextoPeticion(ip="10.9.9.10"))


def test_login_correcto_reinicia_el_contador_del_usuario(client: TestClient, crear_usuario):
    crear_usuario("eli")
    for _ in range(4):
        login(client, "eli", "incorrecta-123")
    assert login(client, "eli").status_code == 200
    for _ in range(4):
        assert login(client, "eli", "incorrecta-123").status_code == 401
    assert login(client, "eli").status_code == 200


def test_validacion_en_espanol(client: TestClient):
    respuesta = client.post(f"{API}/auth/login", json={"username": "x"})
    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert detalle[0]["loc"] == ["body", "password"]
    assert detalle[0]["msg"] == "Este campo es obligatorio."
    assert "input" not in detalle[0]  # nunca se devuelve lo enviado (podría ser una contraseña)


# --- Access token -------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
def test_access_token_invalido_o_vencido_da_401(client: TestClient, crear_usuario):
    usuario = crear_usuario("fede")
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers=bearer("no-es-un-jwt")).status_code == 401

    claims = jwt.decode(crear_access_token(usuario.id, 0)[0], options={"verify_signature": False})
    secreto = settings.jwt_secret.get_secret_value()
    for cambio in ({"aud": "otra-app"}, {"iss": "otro"}, {"typ": "refresh"}, {"ver": 5}):
        token = jwt.encode({**claims, **cambio}, secreto, ALGORITMO_JWT)
        assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 401
    sin_firma = jwt.encode(claims, key=None, algorithm="none")
    assert client.get(f"{API}/auth/me", headers=bearer(sin_firma)).status_code == 401
    otro_alg = jwt.encode(claims, secreto, algorithm="HS512")
    assert client.get(f"{API}/auth/me", headers=bearer(otro_alg)).status_code == 401

    token = token_de(client, "fede")
    with time_machine.travel(ahora_utc() + timedelta(minutes=31)):
        respuesta = client.get(f"{API}/auth/me", headers=bearer(token))
    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Sesión no válida o vencida"}


# --- Refresh ------------------------------------------------------------------

def test_refresh_rota_la_cookie(client: TestClient, crear_usuario, db: Session):
    crear_usuario("gabi")
    rt1 = login(client, "gabi").cookies["rt"]
    respuesta = _refresh(client, rt1)
    assert respuesta.status_code == 200, respuesta.text
    rt2 = respuesta.cookies["rt"]
    assert rt2 and rt2 != rt1
    assert respuesta.json()["usuario"]["username"] == "gabi"
    nuevo_access = respuesta.json()["access_token"]
    assert client.get(f"{API}/auth/me", headers=bearer(nuevo_access)).status_code == 200
    # El nuevo sirve; las sesiones son de la misma familia.
    assert _refresh(client, rt2).status_code == 200
    assert len(set(db.scalars(select(SesionRefresh.familia)))) == 1


def test_refresh_exige_cabecera_y_origen_valido(client: TestClient, crear_usuario):
    crear_usuario("hugo")
    rt = login(client, "hugo").cookies["rt"]
    sin_cabecera = _refresh(client, rt, headers={})
    assert sin_cabecera.status_code == 403
    assert sin_cabecera.json() == {"detail": "Solicitud no permitida"}
    otro_origen = _refresh(client, rt, headers={**CABECERA_FETCH, "Origin": "https://malo.example"})
    assert otro_origen.status_code == 403
    ok = _refresh(client, rt, headers={**CABECERA_FETCH, "Origin": settings.frontend_url})
    assert ok.status_code == 200


def test_refresh_sin_cookie_o_desconocida_da_401_y_borra_cookie(client: TestClient):
    assert _refresh(client, None).status_code == 401
    respuesta = _refresh(client, "token-inventado")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Sesión no válida o vencida"}
    assert "Max-Age=0" in respuesta.headers["set-cookie"]


def test_reuso_dentro_de_la_gracia_devuelve_un_sucesor(client: TestClient, crear_usuario):
    crear_usuario("ines")
    rt1 = login(client, "ines").cookies["rt"]
    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        rt2 = _refresh(client, rt1).cookies["rt"]
        reloj.shift(timedelta(seconds=20))
        otra_pestana = _refresh(client, rt1)
        assert otra_pestana.status_code == 200
        rt3 = otra_pestana.cookies["rt"]
        assert rt3 not in (rt1, rt2)
        # Ambas pestañas siguen con sesión válida.
        assert _refresh(client, rt2).status_code == 200
        assert _refresh(client, rt3).status_code == 200


def test_reuso_fuera_de_la_gracia_revoca_la_familia(client: TestClient, crear_usuario, db: Session):
    crear_usuario("juan")
    rt1 = login(client, "juan").cookies["rt"]
    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        rt2 = _refresh(client, rt1).cookies["rt"]
        reloj.shift(timedelta(seconds=31))
        assert _refresh(client, rt1).status_code == 401  # token robado
        assert _refresh(client, rt2).status_code == 401  # toda la familia queda revocada
    db.expire_all()
    assert all(s.revocado_at is not None for s in db.scalars(select(SesionRefresh)))


def test_refresh_de_usuario_desactivado_falla(client: TestClient, crear_usuario, db: Session):
    usuario = crear_usuario("kike")
    rt = login(client, "kike").cookies["rt"]
    usuario.activo = False
    db.commit()
    assert _refresh(client, rt).status_code == 401


def test_refresh_vencido_falla(client: TestClient, crear_usuario):
    crear_usuario("lia")
    rt = login(client, "lia").cookies["rt"]
    with time_machine.travel(ahora_utc() + timedelta(days=7, seconds=1)):
        assert _refresh(client, rt).status_code == 401


# --- Logout -------------------------------------------------------------------

def test_logout_revoca_y_borra_cookie(client: TestClient, crear_usuario, db: Session):
    crear_usuario("mario")
    rt = login(client, "mario").cookies["rt"]
    client.cookies.clear()
    sin_cabecera = client.post(f"{API}/auth/logout", headers={"Cookie": f"rt={rt}"})
    assert sin_cabecera.status_code == 403
    respuesta = client.post(f"{API}/auth/logout", headers={**CABECERA_FETCH, "Cookie": f"rt={rt}"})
    assert respuesta.status_code == 204
    cookie = respuesta.headers["set-cookie"]
    assert cookie.startswith("rt=") and "Max-Age=0" in cookie and "Path=/api/v1/auth" in cookie
    assert _refresh(client, rt).status_code == 401
    acciones = set(db.scalars(select(Auditoria.accion).where(Auditoria.username == "mario")))
    assert "logout" in acciones
    # Sin cookie también responde 204 (idempotente).
    client.cookies.clear()
    assert client.post(f"{API}/auth/logout", headers=CABECERA_FETCH).status_code == 204
