import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_shipped_ratios_cover_all_kinds_and_profiles():
    r = json.loads((ROOT / "dracoconv" / "data" / "ratios.json").read_text(encoding="utf-8"))
    for kind in ("stl", "obj", "ply", "3mf", "zip"):
        assert {"lossless", "q14", "q16", "q20", "q25"} <= set(r[kind])
        assert all(0 < v < 2 for v in r[kind].values())
        assert r[kind]["q14"] <= r[kind]["q16"] <= r[kind]["q20"] <= r[kind]["q25"]


def test_calibrate_writes_measured_ratios(model_tree, tmp_path):
    out = tmp_path / "ratios.json"
    out.write_text(json.dumps({"zip": {"lossless": 0.45}}), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "calibrate.py"), str(model_tree), "--out", str(out), "--per-class", "2"],
        capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["_meta"]["calibrated"] is True and r["_meta"]["kinds"] == ["obj", "stl"]
    assert 0 < r["stl"]["q14"] < r["stl"]["lossless"] < 1 and r["zip"] == {"lossless": 0.45}
    assert not list(model_tree.rglob("*.drc"))
