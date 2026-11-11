import threading
from dataclasses import replace

import pytest

from dracoconv.io.sniff import FileKind
from dracoconv.quality import error_bound_mm
from dracoconv.sampling import quality_sample
from dracoconv.scan import Inventory, ScanOptions, scan
from dracoconv.settings import EncodeSettings

ALL = ScanOptions(kinds=frozenset(FileKind))


def test_lossless_sample_is_identical(model_tree):
    q = quality_sample(scan([model_tree], ALL), EncodeSettings(), seed=1)
    assert q.files == 4 and q.identical and q.worst_error_mm == 0 and q.collapsed == 0
    assert q.median_extent_mm == pytest.approx(70.0, abs=11.0)


def test_quantized_sample_reports_errors_and_curve(model_tree):
    settings = replace(EncodeSettings(), position_bits=12)
    q = quality_sample(scan([model_tree], ALL), settings, seed=1)
    assert not q.identical and 0 < q.median_error_mm <= q.worst_error_mm < 0.03
    assert [p.bits for p in q.curve] == list(range(8, 30))
    assert q.curve[0].max_error_mm > q.curve[-1].max_error_mm
    assert all(0 < pct < 100 for pct in q.curve_size_pct) and len(q.curve_size_pct) == len(q.curve)
    assert q.curve_size_pct[0] < q.curve_size_pct[-1] and q.curve_extent_mm > 0


def test_max_files_limits_the_sample(model_tree):
    assert quality_sample(scan([model_tree], ALL), EncodeSettings(), max_files=2, seed=1).files == 2


def test_unreadable_files_are_left_out(model_tree):
    (model_tree / "bad.stl").write_bytes(b"garbage" * 30)
    q = quality_sample(scan([model_tree], ALL), EncodeSettings(), max_files=10, seed=1)
    assert q.files == 4


def test_empty_inventory_and_stop():
    assert quality_sample(Inventory(), EncodeSettings()).files == 0
    stop = threading.Event()
    stop.set()
    assert quality_sample(Inventory(), EncodeSettings(), stop=stop).curve == []
