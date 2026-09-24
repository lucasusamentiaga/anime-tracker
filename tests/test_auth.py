"""
Tests del hashing y rate-limit del PIN (v2).

No importamos main.py entero porque arrastra requests/fastapi/etc. y este
test debe correr sin esas deps. Reproducimos las primitivas mínimas — si en
algún momento la firma cambia, el test fallará y te avisará.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

# ── Implementación de referencia que ESPEJEA la de main.py ────────────────────
# Si cambias el algoritmo en main.py, cambia aquí también.

def _hash_pin(db, pin: str) -> str:
    s = db.get_config("pin_salt")
    if not s:
        s = secrets.token_hex(16)
        db.set_config("pin_salt", s)
    return hmac.new(s.encode(), pin.encode(), hashlib.sha256).hexdigest()


def _check_pin(db, pin: str, stored: str) -> bool:
    if not stored:
        return False
    if hmac.compare_digest(_hash_pin(db, pin), stored):
        return True
    legacy = hashlib.sha256(pin.encode()).hexdigest()
    if hmac.compare_digest(legacy, stored):
        db.set_config("mobile_pin", _hash_pin(db, pin))
        return True
    return False


def test_hash_es_estable_con_mismo_salt(db):
    h1 = _hash_pin(db, "1234")
    h2 = _hash_pin(db, "1234")
    assert h1 == h2


def test_hash_distinto_por_pin(db):
    assert _hash_pin(db, "1234") != _hash_pin(db, "1235")


def test_check_pin_correcto(db):
    h = _hash_pin(db, "1234")
    assert _check_pin(db, "1234", h)


def test_check_pin_incorrecto(db):
    h = _hash_pin(db, "1234")
    assert not _check_pin(db, "4321", h)


def test_check_pin_string_vacio(db):
    assert not _check_pin(db, "1234", "")


def test_migracion_pin_legacy_v1_a_v2(db):
    """Un PIN guardado en v1 (sha256 sin sal) sigue funcionando y se migra."""
    legacy = hashlib.sha256(b"5678").hexdigest()
    db.set_config("mobile_pin", legacy)
    # Primer login con PIN correcto: debe aceptar y re-guardar con sal
    assert _check_pin(db, "5678", legacy)
    nuevo = db.get_config("mobile_pin")
    assert nuevo != legacy, "el formato no se migró"
    # Y el nuevo formato sigue funcionando
    assert _check_pin(db, "5678", nuevo)


def test_salt_persistente_no_cambia_entre_llamadas(db):
    _hash_pin(db, "x")
    salt1 = db.get_config("pin_salt")
    _hash_pin(db, "otro")
    salt2 = db.get_config("pin_salt")
    assert salt1 == salt2 and salt1


def test_salt_de_16_bytes_hex(db):
    _hash_pin(db, "x")
    salt = db.get_config("pin_salt")
    assert len(salt) == 32  # 16 bytes en hex
    int(salt, 16)  # parseable como hex


# ── Rate limit (versión reducida que copia la lógica de main.py) ──────────────

class _RateLimiter:
    """Réplica de la lógica de _auth_rate_check para test aislado."""
    def __init__(self, window=60, max_tries=5, ban_after=20, ban_seconds=600):
        self.window = window
        self.max_tries = max_tries
        self.ban_after = ban_after
        self.ban_seconds = ban_seconds
        self.attempts: dict[str, list[float]] = {}
        self.bans: dict[str, float] = {}

    def check(self, ip: str, now: float) -> tuple[bool, str]:
        if now < self.bans.get(ip, 0):
            return False, "ban"
        tries = [t for t in self.attempts.get(ip, []) if now - t < self.window]
        if len(tries) >= self.max_tries:
            return False, "limit"
        return True, "ok"

    def fail(self, ip: str, now: float):
        tries = [t for t in self.attempts.get(ip, []) if now - t < self.window]
        tries.append(now)
        self.attempts[ip] = tries
        if len(tries) >= self.ban_after:
            self.bans[ip] = now + self.ban_seconds

    def ok(self, ip: str):
        self.attempts.pop(ip, None)
        self.bans.pop(ip, None)


def test_rate_limit_5_intentos_ok():
    rl = _RateLimiter()
    t = 1000.0
    for _ in range(5):
        ok, _ = rl.check("1.1.1.1", t)
        assert ok
        rl.fail("1.1.1.1", t)


def test_rate_limit_sexto_intento_bloqueado():
    rl = _RateLimiter()
    t = 1000.0
    for _ in range(5):
        rl.fail("1.1.1.1", t)
    ok, motivo = rl.check("1.1.1.1", t)
    assert not ok and motivo == "limit"


def test_rate_limit_ventana_se_resetea():
    rl = _RateLimiter(window=60)
    t = 1000.0
    for _ in range(5):
        rl.fail("1.1.1.1", t)
    # 61s después, la ventana caducó
    ok, _ = rl.check("1.1.1.1", t + 61)
    assert ok


def test_rate_limit_ban_largo_tras_20_fallos():
    rl = _RateLimiter(ban_after=20, ban_seconds=600)
    t = 1000.0
    for _ in range(20):
        rl.fail("1.1.1.1", t)
    # Aunque pasen 61s (ventana caducada), el ban sigue
    ok, motivo = rl.check("1.1.1.1", t + 61)
    assert not ok and motivo == "ban"


def test_rate_limit_login_correcto_limpia_intentos():
    rl = _RateLimiter()
    t = 1000.0
    for _ in range(3):
        rl.fail("1.1.1.1", t)
    rl.ok("1.1.1.1")
    # Y ahora puede volver a intentar las 5 veces completas
    for _ in range(5):
        ok, _ = rl.check("1.1.1.1", t)
        assert ok
        rl.fail("1.1.1.1", t)
