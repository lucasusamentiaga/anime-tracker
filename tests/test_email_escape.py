"""Los emails de notificación escapan datos externos (nombre, imagen, géneros)."""
from __future__ import annotations


def test_emails_escapan_html(db, monkeypatch):
    import main
    enviados = []
    monkeypatch.setattr(main, "_sync_bg", lambda fn, *a: enviados.append(a))
    db.set_config("email_notif", "yo@ejemplo.com")
    anime = {"nombre": "<script>x</script>", "imagen": 'a" onerror="y',
             "genero": "<b>Acción</b>", "notif_activa": 1}
    main._enviar_notif_nuevo_episodio(anime, 3)
    main._notif_enviar_nuevo_disponible(anime, 1, 2, "yo@ejemplo.com")
    db.set_config("email_notif", "")
    assert len(enviados) == 2
    for _email, asunto, html in enviados:
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert 'onerror="y' not in html
        assert "<b>Acción</b>" not in html
        assert "<script>x</script>" in asunto   # el asunto es texto plano
