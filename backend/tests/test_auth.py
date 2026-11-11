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
from app.core.security import hash_token
from app.models import Auditoria, IntentoLogin, SesionRefresh
from app.services import auth_service, rate_limit
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
    filas = list(db.scalars(select(Auditoria).where(Auditoria.accion == "login_fallido")))
    motivos = {a.username: a.detalle["motivo"] for a in filas}
    assert motivos == {
        "beto": "password_incorrecta",
        None: "usuario_inexistente",  # nunca se guarda lo escrito (podría ser una contraseña)
        "inactivo": "usuario_inactivo",
    }
    # Los intentos de usuarios existentes quedan a su nombre (usuario_id y rol).
    assert all(a.usuario_id is not None and a.rol for a in filas if a.username)
    assert not any("no_existe" in str(a.detalle) for a in filas)


def test_texto_escrito_en_usuario_no_queda_en_la_bd(client: TestClient, db: Session):
    """Si alguien escribe su contraseña en el campo usuario, no queda en auditoría ni en
    intento_login (inmutable la primera, visible para admin y subgerente)."""
    escrito = "MiClaveSecreta2026"
    assert login(client, escrito, "x").status_code == 401
    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "login_fallido")).one()
    assert fila.username is None and fila.usuario_id is None
    intento = db.scalars(select(IntentoLogin)).one()
    assert intento.username_intentado != escrito.lower()
    assert len(intento.username_intentado) == 64  # HMAC-SHA256 en hex
    # El conteo sigue funcionando con el valor protegido (mayúsculas y espacios normalizados).
    assert rate_limit.clave_usuario(f" {escrito.upper()} ") == intento.username_intentado


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


def _sesiones_activas(db: Session) -> int:
    db.expire_all()
    return db.scalar(
        select(func.count()).select_from(SesionRefresh).where(
            SesionRefresh.revocado_at.is_(None), SesionRefresh.reemplazado_por.is_(None)
        )
    )


def test_reuso_dentro_de_la_gracia_devuelve_un_sucesor(client: TestClient, crear_usuario, db: Session):
    """Respuesta perdida: el cliente reintenta con el token anterior y recibe un sucesor."""
    crear_usuario("ines")
    rt1 = login(client, "ines").cookies["rt"]
    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        rt2 = _refresh(client, rt1).cookies["rt"]  # esta respuesta "se pierde"
        reloj.shift(timedelta(seconds=20))
        reintento = _refresh(client, rt1)
        assert reintento.status_code == 200
        rt3 = reintento.cookies["rt"]
        assert rt3 not in (rt1, rt2)
        assert _sesiones_activas(db) == 1  # nunca más de una hoja activa por familia
        # El sucesor de gracia sigue rotando con normalidad.
        rt4 = _refresh(client, rt3).cookies["rt"]
        assert _refresh(client, rt4).status_code == 200


def test_segundo_reuso_en_la_gracia_revoca_la_familia(client: TestClient, crear_usuario, db: Session):
    crear_usuario("ines2")
    rt1 = login(client, "ines2").cookies["rt"]
    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        _refresh(client, rt1)
        reloj.shift(timedelta(seconds=5))
        primero = _refresh(client, rt1)
        assert primero.status_code == 200
        rt_gracia = primero.cookies["rt"]
        reloj.shift(timedelta(seconds=5))
        assert _refresh(client, rt1).status_code == 401  # la gracia ya se usó: es un robo
        assert _refresh(client, rt_gracia).status_code == 401
    db.expire_all()
    assert all(s.revocado_at is not None for s in db.scalars(select(SesionRefresh)))


def test_hoja_revocada_por_la_gracia_revoca_la_familia(client: TestClient, crear_usuario, db: Session):
    """Ladrón y dueño con la misma familia: quien use la hoja que la gracia revocó la delata."""
    crear_usuario("ines3")
    rt1 = login(client, "ines3").cookies["rt"]
    with time_machine.travel(ahora_utc(), tick=False) as reloj:
        rt2 = _refresh(client, rt1).cookies["rt"]  # el dueño rota
        reloj.shift(timedelta(seconds=10))
        rt3 = _refresh(client, rt1).cookies["rt"]  # otro usa rt1 dentro de la gracia
        assert _refresh(client, rt2).status_code == 401  # el dueño vuelve con rt2
        assert _refresh(client, rt3).status_code == 401  # la familia quedó revocada
    db.expire_all()
    assert all(s.revocado_at is not None for s in db.scalars(select(SesionRefresh)))


def test_varios_reusos_en_la_gracia_entregan_un_solo_sucesor(
    client: TestClient, crear_usuario, db: Session
):
    crear_usuario("ines4")
    rt1 = login(client, "ines4").cookies["rt"]
    with time_machine.travel(ahora_utc(), tick=False):
        _refresh(client, rt1)
        estados = [_refresh(client, rt1).status_code for _ in range(5)]
    assert estados == [200, 401, 401, 401, 401]
    assert _sesiones_activas(db) == 0


def test_sesion_se_desliza_con_tope_de_30_dias(client: TestClient, crear_usuario, db: Session):
    crear_usuario("ines5")
    inicio = ahora_utc()
    with time_machine.travel(inicio, tick=False) as reloj:
        rt = login(client, "ines5").cookies["rt"]
        for _ in range(4):  # día 6, 12, 18, 24: cada uso extiende 7 días
            reloj.shift(timedelta(days=6))
            respuesta = _refresh(client, rt)
            assert respuesta.status_code == 200
            rt = respuesta.cookies["rt"]
        ultima = db.scalars(
            select(SesionRefresh).where(SesionRefresh.token_hash == hash_token(rt))
        ).one()
        assert ultima.expira_at <= inicio + timedelta(days=30, seconds=1)
        reloj.shift(timedelta(days=6, seconds=1))  # día 30: tope absoluto desde el login
        assert _refresh(client, rt).status_code == 401


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


# --- Límite sin carreras ------------------------------------------------------

def test_limite_resiste_intentos_simultaneos(engine):
    """25 intentos a la vez (mismo usuario e IP), cada uno con commit real en su conexión y una
    demora como la de argon2: no pasan más de 5 (antes pasaban ~13)."""
    import threading
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import delete
    from sqlalchemy.orm import Session as SesionOrm

    from app.db.session import crear_engine
    from app.models.enums import TipoIntento
    from tests.conftest import TEST_DATABASE_URL

    usuario = f"carrera_{uuid.uuid4().hex[:8]}"
    ip = "10.66.0.1"
    hilos = 25
    barrera = threading.Barrier(hilos)
    motor = crear_engine(TEST_DATABASE_URL, modo_pool="null")

    def intentar() -> bool:
        with SesionOrm(motor, expire_on_commit=False) as sesion:
            barrera.wait()
            try:
                rate_limit.reservar(sesion, TipoIntento.login, usuario=usuario, ip=ip)
            except LimiteExcedido:
                return False
            time.sleep(0.3)  # verificación de la contraseña (argon2)
            return True  # contraseña incorrecta: el intento queda como fallo

    try:
        with ThreadPoolExecutor(max_workers=hilos) as ejecutor:
            resultados = list(ejecutor.map(lambda _i: intentar(), range(hilos)))
        assert 1 <= sum(resultados) <= 5, resultados
        with SesionOrm(motor) as sesion:
            fallos = sesion.scalar(
                select(func.count()).select_from(IntentoLogin).where(
                    IntentoLogin.username_intentado == rate_limit.clave_usuario(usuario)
                )
            )
        assert fallos == sum(resultados)  # los rechazados no quedan registrados
    finally:
        with SesionOrm(motor) as sesion:
            sesion.execute(delete(IntentoLogin).where(IntentoLogin.ip == ip))
            sesion.commit()
        motor.dispose()
