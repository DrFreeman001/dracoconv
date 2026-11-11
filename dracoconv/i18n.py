"""Traduction de tous les textes visibles. Langues : français et anglais."""
from __future__ import annotations

import json
import locale
import os
from functools import lru_cache
from pathlib import Path

LANGUAGES = ("fr", "en")
_current = "fr"


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict[str, str]:
    path = Path(__file__).parent / "locales" / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _windows_locale() -> str | None:
    """Langue d'affichage de Windows, sous la forme « fr_FR »."""
    if os.name == "nt":
        try:
            import ctypes

            return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage())
        except Exception:
            pass
    try:
        return locale.getlocale()[0]
    except Exception:
        return None


def system_language() -> str:
    name = _windows_locale() or ""
    return "fr" if name.lower().startswith("fr") else "en"


def set_language(lang: str) -> None:
    global _current
    if lang not in LANGUAGES:
        raise ValueError(f"langue inconnue : {lang}")
    _current = lang


def get_language() -> str:
    return _current


def all_keys(lang: str) -> set[str]:
    return set(_catalog(lang))


def tr_in(lang: str, key: str, **fmt) -> str:
    text = _catalog(lang)[key]
    return text.format(**fmt) if fmt else text


def tr(key: str, **fmt) -> str:
    return tr_in(_current, key, **fmt)


def reason_text(code: str) -> str:
    """Texte d'une raison. Une note d'archive (« nom: raison, nom: raison ») est traduite morceau par morceau."""
    catalog = _catalog(_current)
    if "reason." + code in catalog:
        return catalog["reason." + code]
    parts = []
    for part in code.split(", "):
        name, separator, reason = part.rpartition(": ")
        translated = catalog.get("reason." + reason)
        parts.append(f"{name}{separator}{translated}" if separator and translated else part)
    return ", ".join(parts)


def format_size(size: float) -> str:
    """Taille lisible : « 73,6 Go » en français, « 73.6 GB » en anglais."""
    value = float(size)
    for unit in ("bytes", "kb", "mb", "gb"):
        if abs(value) < 1024:
            decimals = 0 if unit == "bytes" else (1 if abs(value) >= 10 else 2)
            return f"{format_number(value, decimals)} {tr('unit.' + unit)}"
        value /= 1024
    return f"{format_number(value, 1 if abs(value) >= 10 else 2)} {tr('unit.tb')}"


def format_number(value: float, decimals: int = 3) -> str:
    """Nombre décimal selon la langue : virgule en français, point en anglais."""
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if _current == "fr" else text
