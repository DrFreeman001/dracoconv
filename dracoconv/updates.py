"""Avis de nouvelle version : au plus une requête par jour vers GitHub, anonyme, désactivable.

Seule information envoyée : la requête elle-même (adresse IP, en-tête « User-Agent: dracoconv »). Rien sur les
fichiers ni les réglages. En cas d'échec réseau, rien ne s'affiche et l'essai suivant attend le lendemain.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

from . import __version__
from .config import load_prefs, save_prefs

LATEST = "https://api.github.com/repos/DrFreeman001/dracoconv/releases/latest"
RELEASES = "https://github.com/DrFreeman001/dracoconv/releases/latest"
INTERVAL_S = 24 * 3600


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def enabled() -> bool:
    return bool(load_prefs().get("check_updates", True))


def set_enabled(value: bool) -> None:
    save_prefs({"check_updates": bool(value)})


def due(now: float | None = None) -> bool:
    if os.environ.get("DRACOCONV_NO_UPDATE_CHECK"):  # tests, ou choix de l'administrateur
        return False
    prefs = load_prefs()
    now = time.time() if now is None else now
    return bool(prefs.get("check_updates", True)) and now - float(prefs.get("last_update_check", 0)) >= INTERVAL_S


def newer_version(fetch=None, current: str = __version__) -> str | None:
    """Numéro de la dernière version publiée si elle est plus récente que celle-ci, sinon None."""
    save_prefs({"last_update_check": time.time()})
    try:
        if fetch is None:
            request = urllib.request.Request(LATEST, headers={"User-Agent": "dracoconv", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.load(response)
        else:
            payload = fetch()
        tag = str(payload.get("tag_name", ""))
    except (OSError, ValueError, AttributeError):
        return None
    latest = version_tuple(tag)
    return tag.lstrip("v") if latest and latest > version_tuple(current) else None
