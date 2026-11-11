from dataclasses import replace

import pytest

from dracoconv.i18n import all_keys, get_language, set_language, system_language, tr, tr_in
from dracoconv.params import CATALOG
from dracoconv.settings import (
    PROFILES, EncodeSettings, delete_profile, resolve_bits, save_profile, user_profiles,
)


@pytest.fixture(autouse=True)
def _french():
    set_language("fr")
    yield
    set_language("fr")


def test_locales_have_same_keys():
    assert all_keys("fr") == all_keys("en")


def test_no_empty_translation():
    for lang in ("fr", "en"):
        assert all(tr_in(lang, k).strip() for k in all_keys(lang))


def test_set_and_get_language():
    set_language("en")
    assert get_language() == "en"
    with pytest.raises(ValueError):
        set_language("de")


def test_tr_formats_and_rejects_unknown_key():
    assert tr("param.position_bits.label") == tr_in("fr", "param.position_bits.label")
    assert tr_in("fr", "param.position_bits.label") != tr_in("en", "param.position_bits.label")
    with pytest.raises(KeyError):
        tr("no.such.key")


@pytest.mark.parametrize(
    "windows,expected", [("fr_FR", "fr"), ("fr_CA", "fr"), ("en_US", "en"), ("de_DE", "en"), (None, "en")]
)
def test_system_language(monkeypatch, windows, expected):
    monkeypatch.setattr("dracoconv.i18n._windows_locale", lambda: windows)
    assert system_language() == expected


def test_catalog_ids():
    assert list(CATALOG) == [
        "compression_level", "position_bits", "tolerance_mm", "texcoord_bits", "normal_bits",
        "generic_bits", "skip_attributes", "point_cloud", "preserve_order", "keep_topology", "metadata",
        "preserve_polygons",
    ]


def test_every_param_fully_documented_in_both_languages():
    for lang in ("fr", "en"):
        set_language(lang)
        for spec in CATALOG.values():
            assert spec.label().strip() and spec.tooltip().strip()
            sections = spec.help_sections()
            assert list(sections) == ["what", "size", "quality", "recommended", "orca"]
            assert all(v.strip() for v in sections.values())


def test_help_differs_between_languages():
    for spec in CATALOG.values():
        set_language("fr")
        fr = spec.help_sections()["what"]
        set_language("en")
        assert spec.help_sections()["what"] != fr


def test_tooltip_is_one_sentence():
    for lang in ("fr", "en"):
        set_language(lang)
        assert all(len(s.tooltip()) <= 160 for s in CATALOG.values())


def test_cli_flags_are_unique_kebab_case():
    flags = [s.cli_flag for s in CATALOG.values()]
    assert len(set(flags)) == len(flags) and all(f.startswith("--") and "_" not in f for f in flags)


def test_defaults_match_catalog():
    s = EncodeSettings()
    assert (s.compression_level, s.position_bits, s.texcoord_bits, s.normal_bits, s.generic_bits) == (10, 0, 10, 8, 8)
    assert s.skip_attributes == frozenset({"normal"}) and s.tolerance_mm is None
    assert all(getattr(s, k) == CATALOG[k].default for k in CATALOG)


@pytest.mark.parametrize(
    "bad",
    [dict(position_bits=31), dict(position_bits=-1), dict(compression_level=11), dict(tolerance_mm=0),
     dict(skip_attributes=frozenset({"nope"}))],
)
def test_validate_bounds(bad):
    with pytest.raises(ValueError):
        replace(EncodeSettings(), **bad).validate()


def test_validate_accepts_defaults_and_profiles():
    for s in PROFILES.values():
        s.validate()


def test_json_roundtrip():
    s = replace(EncodeSettings(), position_bits=14, tolerance_mm=0.02, skip_attributes=frozenset({"normal", "color"}))
    assert EncodeSettings.from_json(s.to_json()) == s


def test_profiles():
    assert list(PROFILES) == ["lossless", "tolerance", "fixed_bits", "orca"]
    assert PROFILES["lossless"] == EncodeSettings()
    assert PROFILES["tolerance"].tolerance_mm == 0.001 and PROFILES["fixed_bits"].position_bits == 16
    for lang in ("fr", "en"):
        assert all(tr_in(lang, f"profile.{name}") for name in PROFILES)


def test_resolve_bits():
    assert resolve_bits(EncodeSettings(), 100.0) == 0
    assert resolve_bits(replace(EncodeSettings(), position_bits=14), 100.0) == 14
    assert resolve_bits(replace(EncodeSettings(), tolerance_mm=0.01), 100.0) == 14
    assert resolve_bits(replace(EncodeSettings(), tolerance_mm=0.01, position_bits=20), 100.0) == 14


def test_user_profiles(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = replace(EncodeSettings(), position_bits=18)
    save_profile("mes figurines", s)
    assert user_profiles() == {"mes figurines": s}
    with pytest.raises(ValueError):
        save_profile("lossless", s)
    delete_profile("mes figurines")
    assert user_profiles() == {}
