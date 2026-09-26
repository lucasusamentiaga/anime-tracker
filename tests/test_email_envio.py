"""
Envío real de email (_enviar_email) con un SMTP falso: sin red ni correos reales.

Comprueba lo que rompería un envío de verdad: asuntos con emoji/tildes (smtplib
codifica el mensaje como ASCII), login, errores de credenciales y config vacía.
"""
from __future__ import annotations

import email
import smtplib
from email.header import decode_header, make_header

import pytest


class _FakeSMTP:
    enviados: list = []
    fallar_login = False

    def __init__(self, host, port, timeout=None):
        assert (host, port) == ("smtp.gmail.com", 465)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pwd):
        if _FakeSMTP.fallar_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    def sendmail(self, frm, to, msg):
        msg.encode("ascii")            # lo mismo que hace smtplib con un str
        _FakeSMTP.enviados.append((frm, to, msg))


@pytest.fixture
def main_mod(db, monkeypatch):
    import main
    _FakeSMTP.enviados = []
    _FakeSMTP.fallar_login = False
    monkeypatch.setattr(main.smtplib, "SMTP_SSL", _FakeSMTP)
    db.set_config("gmail_user", "yo@gmail.com")
    db.set_config("gmail_app_pass", "app-pass")
    db.set_config("email_notif", "yo@gmail.com")
    return main


def test_envia_asunto_con_emoji_y_tildes(main_mod):
    ok, msg = main_mod._enviar_email("yo@gmail.com", "📺 Kimetsu — episodio 5 ñ", "<p>Hola ñ</p>")
    assert ok, msg
    frm, to, raw = _FakeSMTP.enviados[0]
    m = email.message_from_string(raw)
    assert str(make_header(decode_header(m["Subject"]))) == "📺 Kimetsu — episodio 5 ñ"
    cuerpo = m.get_payload()[0].get_payload(decode=True).decode("utf-8")
    assert "Hola ñ" in cuerpo


def test_email_de_prueba(main_mod):
    ok, _ = main_mod._enviar_email_prueba()
    assert ok and len(_FakeSMTP.enviados) == 1


def test_credenciales_incorrectas(main_mod):
    _FakeSMTP.fallar_login = True
    ok, msg = main_mod._enviar_email("yo@gmail.com", "x", "y")
    assert not ok and "contraseña de app" in msg


def test_sin_configurar(main_mod, db):
    db.set_config("gmail_app_pass", "")
    assert main_mod._enviar_email("yo@gmail.com", "x", "y") == (False, "Email no configurado")
    assert _FakeSMTP.enviados == []
