"""Ajoute ou met à jour des clés de traduction dans les deux langues à la fois.

Usage : python tools/add_locale_keys.py fichier.json
Le fichier contient {"cle": {"fr": "...", "en": "..."}, ...}. Refuse une clé à laquelle il manque une langue.
"""
import json
import sys
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "dracoconv" / "locales"


def main(source: str) -> int:
    new = json.loads(Path(source).read_text(encoding="utf-8"))
    incomplete = [k for k, v in new.items() if set(v) != {"fr", "en"} or not all(str(t).strip() for t in v.values())]
    if incomplete:
        print("Clés incomplètes :", ", ".join(incomplete))
        return 1
    for lang in ("fr", "en"):
        path = LOCALES / f"{lang}.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        catalog.update({k: v[lang] for k, v in new.items()})
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(new)} clés écrites dans fr.json et en.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
