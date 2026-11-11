"""Mesure les ratios de compression réels d'une collection et les écrit dans un fichier de ratios.

Lecture seule : les fichiers sont encodés en mémoire, rien n'est écrit dans la collection.

Usage : python tools/calibrate.py <racines...> --out dracoconv/data/ratios.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

PROFILES = {"lossless": 0, "q14": 14, "q16": 16, "q20": 20, "q25": 25}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kinds", default="stl,obj,ply")
    parser.add_argument("--per-class", type=int, default=5)
    parser.add_argument("--budget", type=float, default=240.0, help="secondes par profil")
    parser.add_argument("--max-bytes", type=int, default=300 << 20, help="ignore les fichiers plus gros")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    # Les ratios appris ne doivent pas se mêler aux réglages de l'utilisateur pendant le calibrage.
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dracoconv-calibrate-")
    from dracoconv.estimate import sampled
    from dracoconv.io.sniff import FileKind
    from dracoconv.scan import Inventory, ScanOptions, scan
    from dracoconv.settings import EncodeSettings

    kinds = frozenset(FileKind(k.strip()) for k in args.kinds.split(","))
    inventory = scan(args.roots, ScanOptions(kinds=kinds))
    inventory = Inventory([e for e in inventory.entries if e.size <= args.max_bytes], inventory.ignored)
    print(f"{inventory.count()} fichiers, {inventory.total_bytes() / 1e9:.2f} Go", flush=True)

    ratios = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    report = {}
    for name, bits in PROFILES.items():
        started = time.perf_counter()
        settings = replace(EncodeSettings(), position_bits=bits)
        projection = sampled(inventory, settings, per_class=args.per_class, time_budget_s=args.budget, seed=args.seed)
        for kind, part in projection.by_kind.items():
            if part.current_bytes:
                ratio = part.projected_bytes / part.current_bytes
                ratios.setdefault(kind.value, {})[name] = round(ratio, 4)
                report.setdefault(kind.value, {})[name] = {
                    "ratio": round(ratio, 4),
                    "low": round(part.low_bytes / part.current_bytes, 4),
                    "high": round(part.high_bytes / part.current_bytes, 4),
                }
        for path, reason in projection.unreadable.items():
            print(f"  non encodé ({reason}) : {path}", flush=True)
        print(f"{name}: {projection.sampled_files} fichiers encodés en {time.perf_counter() - started:.0f} s — "
              + ", ".join(f"{k} {v[name]['ratio']:.3f}" for k, v in report.items() if name in v), flush=True)
    ratios["_meta"] = {
        "calibrated": True, "date": date.today().isoformat(), "files": inventory.count(),
        "bytes": inventory.total_bytes(), "kinds": sorted(report), "per_class": args.per_class,
        "note": "Ratios mesurés par échantillon sur une collection réelle de modèles d'impression 3D. "
                "Les types absents de « kinds » gardent des valeurs de départ non mesurées.",
    }
    args.out.write_text(json.dumps(ratios, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
