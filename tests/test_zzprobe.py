import os
import tempfile


def test_probe():
    print("\nTMPDIR env:", os.environ.get("TMPDIR"))
    print("gettempdir:", tempfile.gettempdir())
    d = tempfile.mkdtemp(prefix="probe_")
    print("mkdtemp ->", d)
