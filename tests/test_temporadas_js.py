"""v2.16.3: etiquetas de temporada de las carpetas (static/temporadas.js)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "static" / "temporadas.js"


def _etiquetas(animes, base):
    if not shutil.which("node"):
        pytest.skip("sin node")
    code = (f"const f=require({json.dumps(str(JS))});"
            f"console.log(JSON.stringify(f({json.dumps(animes)},{json.dumps(base)})))")
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8",
                                     check=True).stdout)


def test_attack_on_titan_tiene_4_temporadas_no_11():
    P = "película"
    nombres = [("Attack on Titan", "25"), ("Shingeki no Kyojin OVA", "3"), ("Shingeki no Kyojin Movie 1", P),
               ("Shingeki no Kyojin: Lost Girls", "3"), ("Shingeki no Kyojin Season 2", "12"),
               ("Attack on Titan Season 3", "12"), ("Attack on Titan Season 3 Part 2", "10"),
               ("Attack on Titan Final Season", "16"), ("Attack on Titan Final Season Part 2", "12"),
               ("Attack on Titan Final Season THE FINAL CHAPTERS Special 1", "1")]
    r = _etiquetas([{"nombre": n, "capitulos": c} for n, c in nombres], "Attack on Titan")
    assert r["etiquetas"] == ["T1", "OVA", "🎬", "Lost Girls", "T2", "T3", "T3 P2", "Final", "Final P2",
                              "Final Esp. 1"]
    assert r["temporadas"] == 4 and r["extras"] == 2


def test_arcos_y_partes_con_nombre():
    r = _etiquetas([{"nombre": "Demon Slayer: Kimetsu no Yaiba", "capitulos": "26"},
                    {"nombre": "Demon Slayer: Kimetsu no Yaiba Swordsmith Village Arc", "capitulos": "11"}], "Demon Slayer")
    assert r["etiquetas"][:2] == ["T1", "Swordsmith Village"]
    r = _etiquetas([{"nombre": "HAIKYU!!", "capitulos": "25"}, {"nombre": "HAIKYU!! TO THE TOP", "capitulos": "13"},
                    {"nombre": "HAIKYU!! TO THE TOP Part 2", "capitulos": "12"}], "HAIKYU!!")
    assert r["etiquetas"] == ["T1", "TO THE TOP", "TO THE TOP P2"] and r["temporadas"] == 2
    r = _etiquetas([{"nombre": "Date A Live", "capitulos": "12"}, {"nombre": "Date A Live Ⅲ", "capitulos": "12"}],
                   "Date A Live")
    assert r["etiquetas"] == ["T1", "T3"]
