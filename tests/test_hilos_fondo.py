"""Los tests no deben lanzar los hilos de fondo de la app: cada test recarga
main y esos hilos acababan escribiendo en la BD de otro test (fallos al azar)."""
import importlib
from unittest.mock import patch

import main


def test_conftest_desactiva_hilos(monkeypatch):
    assert main._sin_hilos_de_fondo()


def test_sin_hilos_no_arranca_ninguno():
    m = importlib.reload(main)
    with patch.object(m.threading, "Thread") as hilo:
        m._start_auto_backup_once()
        m._start_cap200_fix_once()
        m._start_emision_refresh_once()
        m._start_enrich_unknown_eps()
        m._start_notif_daemon_once()
    hilo.assert_not_called()


def test_en_la_app_real_si_arrancan(monkeypatch):
    monkeypatch.delenv("MIRARU_SIN_HILOS_FONDO")
    m = importlib.reload(main)
    with patch.object(m.threading, "Thread") as hilo:
        m._start_auto_backup_once()
        m._start_enrich_unknown_eps()
    assert hilo.call_count == 2
