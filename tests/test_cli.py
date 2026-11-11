import csv
import json

import pytest

from conftest import make_sphere, same_geometry
from dracoconv.cli import main
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.i18n import set_language
from dracoconv.params import CATALOG


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    set_language("fr")
    yield
    set_language("fr")


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_every_param_has_an_option(capsys):
    with pytest.raises(SystemExit) as e:
        main(["encode", "--help"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and all(spec.cli_flag in out for spec in CATALOG.values())


@pytest.mark.parametrize("lang,word", [("fr", "quantification"), ("en", "quantization")])
def test_help_is_translated(capsys, lang, word):
    assert main(["--lang", lang, "params", "position_bits"]) == 0
    out = capsys.readouterr().out
    set_language(lang)
    assert word in out.lower() and all(s in out for s in CATALOG["position_bits"].help_sections().values())
    assert CATALOG["position_bits"].cli_flag in out and "-qp" in out


def test_params_lists_everything(capsys):
    assert main(["params"]) == 0
    out = capsys.readouterr().out
    assert all(spec.cli_flag in out and spec.label() in out for spec in CATALOG.values())


def test_unknown_param_is_a_usage_error(capsys):
    assert main(["params", "nope"]) == 2


def test_scan_json(model_tree, capsys):
    assert main(["scan", str(model_tree), "--json"]) == 0
    d = out_json(capsys)
    assert d["by_kind"]["stl"]["files"] == 3 and d["by_kind"]["zip"]["files"] == 1
    assert d["ignored"]["compiler_obj"] == 1 and d["total_files"] == 5


def test_scan_text_is_translated(model_tree, capsys):
    main(["--lang", "en", "scan", str(model_tree)])
    english = capsys.readouterr().out
    main(["--lang", "fr", "scan", str(model_tree)])
    french = capsys.readouterr().out
    assert "STL" in english and "STL" in french and english != french


def test_estimate_instant_json(model_tree, capsys):
    assert main(["estimate", str(model_tree), "--json"]) == 0
    d = out_json(capsys)
    assert d["method"] == "instant" and 0 < d["projected_bytes"] < d["current_bytes"]


def test_estimate_sample_json(model_tree, capsys):
    assert main(["estimate", str(model_tree), "--sample", "--seed", "1", "--json"]) == 0
    d = out_json(capsys)
    assert d["method"] == "sampled" and d["low_bytes"] <= d["projected_bytes"] <= d["high_bytes"]
    assert d["sampled_files"] == 5 and 0 < d["saved_pct"] < 100


def test_encode_then_decode(model_tree, capsys):
    assert main(["encode", str(model_tree), "--workers", "1", "--json"]) == 0
    d = out_json(capsys)
    assert d["done"] == 5 and d["failed"] == 0 and (model_tree / "a.drc").exists()
    assert main(["decode", str(model_tree / "a.drc"), "--format", "ply", "--workers", "1"]) == 0
    assert (model_tree / "a.ply").exists()


def test_param_options_reach_the_encoder(model_tree, capsys):
    main(["encode", str(model_tree / "a.stl"), "--position-bits", "10", "--workers", "1"])
    quantized = (model_tree / "a.drc").stat().st_size
    out = DracoPyEngine().decode((model_tree / "a.drc").read_bytes())
    assert not same_geometry(out, make_sphere(2, 30.0)) and quantized < 2000


def test_profile_and_skip_options(model_tree, capsys):
    assert main(["encode", str(model_tree / "a.stl"), "--profile", "fixed_bits", "--skip", "normal,color",
                 "--dry-run", "--json"]) == 0
    d = out_json(capsys)
    assert d["settings"]["position_bits"] == 16 and d["settings"]["skip_attributes"] == ["color", "normal"]


def test_dry_run_writes_nothing(model_tree, capsys):
    assert main(["encode", str(model_tree), "--dry-run", "--json"]) == 0
    d = out_json(capsys)
    assert len(d["plan"]) == 5 and not list(model_tree.rglob("*.drc")) and not list(model_tree.rglob("*.drc.zip"))


def test_mirror_mode(model_tree, tmp_path):
    out = tmp_path / "miroir"
    assert main(["encode", str(model_tree), "--originals", "mirror", "--mirror-dir", str(out), "--workers", "1"]) == 0
    assert (out / "sub" / "b.drc").exists() and not (model_tree / "sub" / "b.drc").exists()


def test_replace_needs_flag(model_tree, capsys):
    assert main(["encode", str(model_tree), "--originals", "replace"]) == 2
    assert not list(model_tree.rglob("*.drc"))


def test_mirror_needs_directory(model_tree, capsys):
    assert main(["encode", str(model_tree), "--originals", "mirror"]) == 2


def test_invalid_setting_is_a_usage_error(model_tree, capsys):
    assert main(["encode", str(model_tree), "--position-bits", "31"]) == 2


def test_quality_reports_theoretical_error(model_tree, capsys):
    assert main(["quality", str(model_tree / "a.stl"), "--position-bits", "14", "--json"]) == 0
    d = out_json(capsys)
    assert d["bits"] == 14 and d["theoretical_error_mm"] > 0 and d["max_error_mm"] <= d["error_bound_mm"]
    assert d["max_extent_mm"] == pytest.approx(60.0, abs=0.5) and d["size_after"] < d["size_before"]
    assert d["identical"] is False and d["watertight_before"] is True


def test_quality_lossless_is_identical(model_tree, capsys):
    main(["quality", str(model_tree / "a.stl"), "--json"])
    d = out_json(capsys)
    assert d["identical"] is True and d["max_error_mm"] == 0 and d["bits"] == 0


def test_quality_curve_csv(model_tree, tmp_path, capsys):
    target = tmp_path / "courbe.csv"
    assert main(["quality", str(model_tree / "a.stl"), "--curve", str(target), "--json"]) == 0
    rows = list(csv.DictReader(target.open(encoding="utf-8-sig")))
    assert [int(r["bits"]) for r in rows] == list(range(8, 30))
    assert float(rows[0]["max_error_mm"]) > float(rows[-1]["max_error_mm"])


def test_quality_on_a_folder(model_tree, capsys):
    assert main(["quality", str(model_tree), "--position-bits", "12", "--json"]) == 0
    d = out_json(capsys)
    assert len(d["files"]) == 4 and d["worst_error_mm"] >= d["median_error_mm"] > 0


def test_partial_failure_exit_code(model_tree, capsys):
    (model_tree / "bad.stl").write_bytes(b"garbage" * 30)
    assert main(["encode", str(model_tree), "--workers", "1"]) == 1


def test_journal_option_allows_resume(model_tree, tmp_path, capsys):
    journal = tmp_path / "lot.sqlite"
    assert main(["encode", str(model_tree), "--journal", str(journal), "--workers", "1", "--json"]) == 0
    first = out_json(capsys)
    assert main(["encode", str(model_tree), "--journal", str(journal), "--workers", "1", "--json"]) == 0
    second = out_json(capsys)
    assert first["done"] == second["done"] == 5 and second["journal"] == str(journal)


def test_missing_path_is_a_usage_error(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "absent")]) == 2
