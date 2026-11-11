import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from conftest import make_sphere, make_zip, stl_bytes
from dracoconv.convert import encode_bytes
from dracoconv.estimate import (
    SIZE_CLASS_BOUNDS, instant, load_ratios, profile_key, ratio_for, sampled, save_ratios, size_class,
)
from dracoconv.io import load_mesh
from dracoconv.io.sniff import FileKind
from dracoconv.mesh import Mesh
from dracoconv.scan import FileEntry, Inventory, ScanOptions, scan
from dracoconv.settings import EncodeSettings

STL_ONLY = ScanOptions(kinds=frozenset({FileKind.STL}))


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


@pytest.fixture(scope="module")
def stl_collection(tmp_path_factory) -> Path:
    """40 STL : 30 petits (moins de 1 Mo) et 10 moyens (4 Mo), plus ou moins bruités."""
    root = tmp_path_factory.mktemp("collection")
    rng = np.random.default_rng(7)
    bases = {s: make_sphere(s) for s in (3, 4, 6)}
    for i in range(40):
        base = bases[6] if i >= 30 else bases[3 + i % 2]
        noise = rng.normal(0, 0.02 * (i % 5), base.positions.shape).astype(np.float32)
        mesh = Mesh(base.positions * np.float32(0.5 + i % 4) + noise, base.faces)
        (root / f"m{i:02d}.stl").write_bytes(stl_bytes(mesh))
    return root


@pytest.fixture
def inventory_stl_1gb() -> Inventory:
    return Inventory([FileEntry(Path("X:/gros.stl"), FileKind.STL, 1 << 30, 1.0)])


def test_size_class():
    assert SIZE_CLASS_BOUNDS == (1 << 20, 10 << 20, 100 << 20)
    assert [size_class(s) for s in (10, 1 << 20, 50 << 20, 200 << 20)] == [0, 1, 2, 3]


def test_profile_key():
    assert profile_key(EncodeSettings()) == "lossless"
    assert profile_key(replace(EncodeSettings(), position_bits=14)) == "q14"
    assert profile_key(replace(EncodeSettings(), tolerance_mm=0.01)) == "tol"


def test_shipped_ratios_are_usable():
    ratios = load_ratios()
    assert 0 < ratio_for(ratios, FileKind.STL, EncodeSettings()) < 1
    low = ratio_for(ratios, FileKind.STL, replace(EncodeSettings(), position_bits=12))
    mid = ratio_for(ratios, FileKind.STL, replace(EncodeSettings(), position_bits=18))
    assert 0 < low < mid < ratio_for(ratios, FileKind.STL, EncodeSettings())


def test_instant_applies_ratio(inventory_stl_1gb):
    p = instant(inventory_stl_1gb, EncodeSettings(), ratios={"stl": {"lossless": 0.15}})
    assert p.projected_bytes == pytest.approx(0.15 * p.current_bytes) and p.method == "instant"
    assert p.current_bytes == 1 << 30 and p.saved_bytes == p.current_bytes - p.projected_bytes
    assert p.saved_pct == pytest.approx(85.0) and p.low_bytes < p.projected_bytes < p.high_bytes
    assert p.by_kind[FileKind.STL].files == 1


def test_instant_ignores_already_converted_files():
    inv = Inventory([FileEntry(Path("X:/a.drc"), FileKind.DRC, 1000, 1.0)])
    assert instant(inv, EncodeSettings()).current_bytes == 0


def test_sampled_within_interval_of_truth(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    p = sampled(inv, EncodeSettings(), per_class=6, seed=1)
    truth = sum(len(encode_bytes(load_mesh(e.path), EncodeSettings())[0]) for e in inv.entries)
    assert p.method == "sampled" and p.sampled_files == 12
    assert p.low_bytes <= truth <= p.high_bytes
    assert p.low_bytes < p.projected_bytes < p.high_bytes
    assert abs(p.projected_bytes - truth) < 0.15 * truth


def test_sampling_everything_is_exact(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    p = sampled(inv, EncodeSettings(), per_class=10_000, seed=1)
    truth = sum(len(encode_bytes(load_mesh(e.path), EncodeSettings())[0]) for e in inv.entries)
    assert p.low_bytes == p.projected_bytes == p.high_bytes == truth and p.sampled_files == 40


def test_quantized_projection_is_smaller(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    lossless = sampled(inv, EncodeSettings(), per_class=3, seed=1)
    quantized = sampled(inv, replace(EncodeSettings(), position_bits=14), per_class=3, seed=1)
    assert quantized.projected_bytes < 0.5 * lossless.projected_bytes


def test_time_budget_respected(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    t = time.perf_counter()
    p = sampled(inv, EncodeSettings(), time_budget_s=0.0, seed=1)
    assert time.perf_counter() - t < 5 and p.sampled_files == 1
    assert p.low_bytes < p.projected_bytes < p.high_bytes


def test_stop_event(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    stop = threading.Event()
    stop.set()
    assert sampled(inv, EncodeSettings(), seed=1, stop=stop).sampled_files <= 1


def test_progress_callback(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    seen = []
    sampled(inv, EncodeSettings(), per_class=2, seed=1, on_progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (4, 4)


def test_zip_compared_to_archive_size(tmp_path, dense):
    make_zip(tmp_path / "p.zip", {"d.stl": stl_bytes(dense), "notice.txt": b"x" * 1000})
    inv = scan([tmp_path], ScanOptions(kinds=frozenset({FileKind.ZIP})))
    p = sampled(inv, EncodeSettings(), seed=1)
    assert p.current_bytes == (tmp_path / "p.zip").stat().st_size
    assert 0 < p.projected_bytes < p.current_bytes


def test_unreadable_and_no_gain_files_keep_their_size(tmp_path, cube):
    (tmp_path / "bad.stl").write_bytes(b"garbage" * 100)
    inv = scan([tmp_path], STL_ONLY)
    p = sampled(inv, EncodeSettings(), seed=1)
    assert p.projected_bytes == p.current_bytes == 700


def test_sampled_updates_user_ratios(stl_collection):
    inv = scan([stl_collection], STL_ONLY)
    before = load_ratios()["stl"]["lossless"]
    sampled(inv, EncodeSettings(), per_class=3, seed=1)
    after = load_ratios()["stl"]["lossless"]
    assert 0 < after < 1 and after != before
    assert load_ratios()["obj"] == before_obj()


def before_obj():
    import json
    from importlib.resources import files

    return json.loads(files("dracoconv.data").joinpath("ratios.json").read_text(encoding="utf-8"))["obj"]


def test_save_and_load_ratios():
    save_ratios({"stl": {"lossless": 0.5}})
    assert load_ratios()["stl"]["lossless"] == 0.5
    assert "q14" in load_ratios()["stl"]  # les valeurs livrées complètent celles de l'utilisateur
