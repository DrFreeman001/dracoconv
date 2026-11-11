"""Ligne de commande : dracoconv scan | estimate | quality | encode | decode | params | gui."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import numpy as np

from . import __version__
from .batch import BatchOptions, Journal, build_plan, check_free_space, run
from .config import data_dir
from .convert import SKIP_REASONS, VerifyError, encode_bytes
from .engine import DracoPyEngine, EngineError, select_engine
from .estimate import instant, sampled
from .i18n import format_number, format_size, set_language, system_language, tr
from .io import MODEL_KINDS, FileKind, load_mesh
from .io.paths import long_path
from .mesh import MeshReadError
from .params import CATALOG
from .quality import (
    REFERENCE_MARKS_MM, curve, error_bound_mm, measure, quantization_step_mm, theoretical_error_mm,
)
from .scan import DEFAULT_EXCLUDES, ScanOptions, scan
from .settings import PROFILES, EncodeSettings, resolve_bits, user_profiles

EXIT_OK, EXIT_PARTIAL, EXIT_USAGE = 0, 1, 2
_KIND_ORDER = ("stl", "obj", "ply", "3mf", "zip", "drc")


class UsageError(Exception):
    pass


def _language_from(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return system_language()


def _skip_set(text: str) -> frozenset[str]:
    if text.strip().lower() in ("none", ""):
        return frozenset()
    return frozenset(part.strip().lower() for part in text.split(",") if part.strip())


def _add_param_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Draco")
    for spec in CATALOG.values():
        dest = "param_" + spec.id
        text = spec.tooltip().replace("%", "%%")
        if spec.type == "bool":
            group.add_argument(spec.cli_flag, dest=dest, action=argparse.BooleanOptionalAction, default=None, help=text)
        elif spec.type == "set":
            choices = tr("cli.opt.skip_values", choices=", ".join(spec.choices)).replace("%", "%%")
            group.add_argument(spec.cli_flag, dest=dest, type=_skip_set, default=None, metavar="LIST",
                               help=f"{text} {choices}")
        else:
            group.add_argument(spec.cli_flag, dest=dest, type=int if spec.type == "int" else float, default=None,
                               metavar="N", help=text)


def _add_scan_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="+", type=Path, help=tr("cli.arg.paths"))
    parser.add_argument("--kinds", help=tr("cli.opt.kinds"))
    parser.add_argument("--exclude", action="append", default=[], metavar="NAME", help=tr("cli.opt.exclude"))
    parser.add_argument("--no-zip", action="store_true", help=tr("cli.opt.no_zip"))
    parser.add_argument("--json", action="store_true", help=tr("cli.opt.json"))


def _add_settings_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=sorted(set(PROFILES) | set(user_profiles())), help=tr("cli.opt.profile"))
    parser.add_argument("--engine", choices=("dracopy", "reference"), help=tr("cli.opt.engine"))
    _add_param_options(parser)


def _add_batch_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--originals", choices=("keep", "mirror", "replace"), default="keep", help=tr("cli.opt.originals"))
    parser.add_argument("--mirror-dir", type=Path, help=tr("cli.opt.mirror_dir"))
    parser.add_argument("--replace-originals", action="store_true", help=tr("cli.opt.replace_originals"))
    parser.add_argument("--workers", type=int, help=tr("cli.opt.workers"))
    parser.add_argument("--journal", type=Path, help=tr("cli.opt.journal"))
    parser.add_argument("--dry-run", action="store_true", help=tr("cli.opt.dry_run"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dracoconv", description=tr("cli.description"))
    parser.add_argument("--version", action="version", version=f"dracoconv {__version__}")
    parser.add_argument("--lang", choices=("fr", "en"), help=tr("cli.opt.lang"))
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("scan", help=tr("cli.cmd.scan"), description=tr("cli.cmd.scan"))
    _add_scan_options(p)

    p = commands.add_parser("estimate", help=tr("cli.cmd.estimate"), description=tr("cli.cmd.estimate"))
    _add_scan_options(p)
    _add_settings_options(p)
    p.add_argument("--sample", action="store_true", help=tr("cli.opt.sample"))
    p.add_argument("--per-class", type=int, default=12, help=tr("cli.opt.per_class"))
    p.add_argument("--budget", type=float, default=60.0, help=tr("cli.opt.budget"))
    p.add_argument("--seed", type=int, help=tr("cli.opt.seed"))

    p = commands.add_parser("quality", help=tr("cli.cmd.quality"), description=tr("cli.cmd.quality"))
    _add_scan_options(p)
    _add_settings_options(p)
    p.add_argument("--curve", type=Path, help=tr("cli.opt.curve"))
    p.add_argument("--max-files", type=int, default=10, help=tr("cli.opt.max_files"))
    p.add_argument("--seed", type=int, help=tr("cli.opt.seed"))

    p = commands.add_parser("encode", help=tr("cli.cmd.encode"), description=tr("cli.cmd.encode"))
    _add_scan_options(p)
    _add_settings_options(p)
    _add_batch_options(p)
    p.add_argument("--allow-no-gain", action="store_true", help=tr("cli.opt.allow_no_gain"))

    p = commands.add_parser("decode", help=tr("cli.cmd.decode"), description=tr("cli.cmd.decode"))
    _add_scan_options(p)
    _add_batch_options(p)
    p.add_argument("--format", choices=("stl", "obj", "ply"), default="stl", help=tr("cli.opt.format"))

    p = commands.add_parser("params", help=tr("cli.cmd.params"), description=tr("cli.cmd.params"))
    p.add_argument("name", nargs="?", help=tr("cli.arg.param"))
    p.add_argument("--json", action="store_true", help=tr("cli.opt.json"))

    commands.add_parser("gui", help=tr("cli.cmd.gui"), description=tr("cli.cmd.gui"))
    return parser


def settings_from(args: argparse.Namespace) -> EncodeSettings:
    settings = EncodeSettings()
    profile = getattr(args, "profile", None)
    if profile:
        settings = {**PROFILES, **user_profiles()}[profile]
    overrides = {
        spec.id: getattr(args, "param_" + spec.id)
        for spec in CATALOG.values()
        if getattr(args, "param_" + spec.id, None) is not None
    }
    if "position_bits" in overrides and "tolerance_mm" not in overrides:
        overrides["tolerance_mm"] = None  # des bits explicites remplacent la tolérance du profil
    settings = replace(settings, **overrides)
    try:
        settings.validate()
    except ValueError as exc:
        raise UsageError(tr("cli.error.settings", detail=str(exc))) from exc
    return settings


def _scan(args: argparse.Namespace, default_kinds: frozenset[FileKind]):
    for path in args.paths:
        if not Path(long_path(path)).exists():
            raise UsageError(tr("cli.error.path_missing", path=path))
    kinds = default_kinds
    if args.kinds:
        try:
            kinds = frozenset(FileKind(k.strip().lower()) for k in args.kinds.split(",") if k.strip())
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
    options = ScanOptions(kinds=kinds, exclude_dirs=DEFAULT_EXCLUDES + tuple(args.exclude),
                          look_inside_zips=not args.no_zip)
    return scan(args.paths, options)


def _emit(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _kind_rows(by_kind: dict) -> list[str]:
    return [k for k in _KIND_ORDER if k in by_kind] + sorted(set(by_kind) - set(_KIND_ORDER))


def cmd_scan(args) -> int:
    inv = _scan(args, frozenset(MODEL_KINDS | {FileKind.ZIP, FileKind.DRC}))
    by_kind = {k.value: {"files": len(v), "bytes": sum(e.size for e in v)} for k, v in inv.by_kind().items()}
    data = {"by_kind": by_kind, "ignored": dict(inv.ignored), "total_files": inv.count(), "total_bytes": inv.total_bytes()}
    if args.json:
        _emit(data)
        return EXIT_OK
    print(f"{tr('cli.col.kind'):<14}{tr('cli.col.files'):>10}{tr('cli.col.size'):>14}")
    for kind in _kind_rows(by_kind):
        print(f"{tr('kind.' + kind):<14}{by_kind[kind]['files']:>10}{format_size(by_kind[kind]['bytes']):>14}")
    print(f"{tr('cli.total'):<14}{inv.count():>10}{format_size(inv.total_bytes()):>14}")
    for reason, count in sorted(inv.ignored.items()):
        print(f"{tr('cli.ignored')} : {count} ({tr('reason.' + reason)})")
    return EXIT_OK


def _projection_dict(p) -> dict:
    return {
        "method": p.method, "current_bytes": p.current_bytes, "projected_bytes": p.projected_bytes,
        "low_bytes": p.low_bytes, "high_bytes": p.high_bytes, "saved_bytes": p.saved_bytes,
        "saved_pct": round(p.saved_pct, 2), "sampled_files": p.sampled_files,
        "by_kind": {k.value: asdict(v) for k, v in p.by_kind.items()},
        "no_gain": [str(x) for x in p.no_gain],
    }


def cmd_estimate(args) -> int:
    settings = settings_from(args)
    inv = _scan(args, frozenset(MODEL_KINDS | {FileKind.ZIP}))
    if args.sample:
        projection = sampled(inv, settings, per_class=args.per_class, time_budget_s=args.budget, seed=args.seed)
    else:
        projection = instant(inv, settings)
    data = _projection_dict(projection)
    if args.json:
        _emit(data)
        return EXIT_OK
    method = tr("method.sampled", n=projection.sampled_files) if projection.method == "sampled" else tr("method.instant")
    print(f"{tr('cli.estimate.method')} : {method}")
    print(f"{tr('cli.estimate.current')} : {format_size(projection.current_bytes)}")
    print(f"{tr('cli.estimate.projected')} : {format_size(projection.projected_bytes)}")
    print(f"{tr('cli.estimate.saved')} : {format_size(projection.saved_bytes)} ({format_number(projection.saved_pct, 1)} %)")
    print(f"{tr('cli.estimate.margin')} : "
          + tr("cli.estimate.range", low=format_size(projection.low_bytes), high=format_size(projection.high_bytes)))
    print(f"{tr('cli.col.kind'):<14}{tr('cli.col.files'):>10}{tr('cli.col.size'):>14}{tr('cli.col.projected'):>14}")
    for kind in _kind_rows(data["by_kind"]):
        row = data["by_kind"][kind]
        print(f"{tr('kind.' + kind):<14}{row['files']:>10}{format_size(row['current_bytes']):>14}"
              f"{format_size(row['projected_bytes']):>14}")
    if projection.no_gain:
        print(f"{tr('cli.estimate.no_gain')} : {len(projection.no_gain)}")
    return EXIT_OK


def _quality_of(path: Path, settings: EncodeSettings, prefer: str | None) -> dict:
    mesh = load_mesh(path)
    extent = mesh.max_extent()
    bits = resolve_bits(settings, extent)
    data, _ = encode_bytes(mesh, settings, prefer)
    report = measure(mesh, DracoPyEngine().decode(data))
    return {
        "file": str(path), "max_extent_mm": extent, "bits": bits,
        "step_mm": quantization_step_mm(extent, bits),
        "theoretical_error_mm": theoretical_error_mm(extent, bits),
        "error_bound_mm": error_bound_mm(mesh, bits),
        "max_error_mm": report.max_error_mm, "rms_error_mm": report.rms_error_mm,
        "identical": report.identical,
        "size_before": mesh.source_size, "size_after": len(data),
        "triangles_before": report.triangles_before, "triangles_after": report.triangles_after,
        "degenerate_created": report.degenerate_created,
        "watertight_before": report.watertight_before, "watertight_after": report.watertight_after,
        "volume_change_pct": report.volume_change_pct,
    }


def _mm(value: float) -> str:
    return f"{format_number(value, 6)} mm"


def _print_quality(q: dict) -> None:
    yes_no = lambda v: tr("value.yes") if v else tr("value.no")  # noqa: E731
    print(f"{tr('cli.quality.file')} : {q['file']}")
    print(f"  {tr('cli.quality.extent')} : {format_number(q['max_extent_mm'], 2)} mm")
    bits = tr("cli.quality.no_quantization") if q["bits"] == 0 else str(q["bits"])
    print(f"  {tr('cli.quality.bits')} : {bits}")
    if q["bits"]:
        print(f"  {tr('cli.quality.step')} : {_mm(q['step_mm'])}")
        print(f"  {tr('cli.quality.theoretical')} : {_mm(q['theoretical_error_mm'])}")
    print(f"  {tr('cli.quality.measured')} : {_mm(q['max_error_mm'])}")
    print(f"  {tr('cli.quality.rms')} : {_mm(q['rms_error_mm'])}")
    print(f"  {tr('cli.quality.identical')} : {yes_no(q['identical'])}")
    print(f"  {tr('cli.quality.size')} : {format_size(q['size_before'])} -> {format_size(q['size_after'])}")
    print(f"  {tr('cli.quality.collapsed')} : {q['degenerate_created']}")
    print(f"  {tr('cli.quality.watertight')} : {yes_no(q['watertight_before'])} / {yes_no(q['watertight_after'])}")
    if q["volume_change_pct"] is not None:
        print(f"  {tr('cli.quality.volume')} : {format_number(q['volume_change_pct'], 4)} %")


def cmd_quality(args) -> int:
    settings = settings_from(args)
    inv = _scan(args, frozenset(MODEL_KINDS))
    files = [e.path for e in inv.entries]
    if not files:
        raise UsageError(tr("cli.error.nothing"))
    single = len(args.paths) == 1 and Path(long_path(args.paths[0])).is_file()
    if len(files) > args.max_files:
        rng = np.random.default_rng(args.seed)
        files = [files[i] for i in sorted(rng.permutation(len(files))[: args.max_files])]
    results, failed = [], 0
    for path in files:
        try:
            results.append(_quality_of(path, settings, args.engine))
        except (MeshReadError, EngineError, VerifyError, OSError) as exc:
            failed += 1
            print(f"{path}: {exc}", file=sys.stderr)
    if not results:
        return EXIT_PARTIAL
    if args.curve:
        mesh = load_mesh(Path(results[0]["file"]))
        engine = select_engine(replace(settings, position_bits=14, tolerance_mm=None), args.engine)
        with open(long_path(args.curve), "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["bits", "size_bytes", "theoretical_error_mm", "max_error_mm"])
            for point in curve(mesh, engine, settings, range(8, engine.max_position_bits + 1)):
                writer.writerow([point.bits, point.size_bytes, point.theoretical_error_mm, point.max_error_mm])
    if single:
        data = results[0]
    else:
        errors = [r["max_error_mm"] for r in results]
        data = {"files": results, "median_error_mm": statistics.median(errors), "worst_error_mm": max(errors)}
    if args.json:
        _emit(data)
    else:
        for result in results:
            _print_quality(result)
        if not single:
            print(f"{tr('cli.quality.median')} : {_mm(data['median_error_mm'])}")
            print(f"{tr('cli.quality.worst')} : {_mm(data['worst_error_mm'])}")
        marks = REFERENCE_MARKS_MM
        print(tr("cli.quality.marks", layer=format_number(marks["layer_height"], 1),
                 nozzle=format_number(marks["nozzle"], 1), cad=format_number(marks["cad_tolerance"], 2)))
        if args.curve:
            print(tr("cli.quality.curve_written", path=args.curve))
    return EXIT_PARTIAL if failed else EXIT_OK


def _batch(args, direction: str, settings: EncodeSettings) -> int:
    if args.originals == "replace" and not args.replace_originals:
        raise UsageError(tr("cli.error.replace"))
    if args.originals == "mirror" and args.mirror_dir is None:
        raise UsageError(tr("cli.error.mirror"))
    options = BatchOptions(
        direction=direction, originals=args.originals, mirror_dir=args.mirror_dir,
        confirm_replace=args.replace_originals, workers=args.workers,
        output_format=getattr(args, "format", "stl"), prefer_engine=getattr(args, "engine", None),
        skip_if_no_gain=not getattr(args, "allow_no_gain", False),
    )
    wanted = MODEL_KINDS | {FileKind.ZIP} if direction == "encode" else {FileKind.DRC, FileKind.ZIP}
    inv = _scan(args, frozenset(wanted))
    items = build_plan(inv, list(args.paths), settings, options)
    todo = [i for i in items if not i.skip_reason]
    if args.dry_run:
        data = {
            "settings": json.loads(settings.to_json()),
            "plan": [{"src": str(i.src), "dst": str(i.dst), "kind": i.kind.value, "size": i.size,
                      "warning": i.warning, "skip_reason": i.skip_reason} for i in items],
        }
        if args.json:
            _emit(data)
        else:
            print(tr("cli.batch.plan", n=len(todo), size=format_size(sum(i.size for i in todo))))
            for item in items:
                extra = item.skip_reason or item.warning
                label = tr(("reason." if item.skip_reason else "warning.") + extra) if extra else ""
                print(f"{item.src} -> {item.dst}" + (f"  [{label}]" if label else ""))
        return EXIT_OK
    journal_path = args.journal or data_dir() / "journals" / f"{datetime.now():%Y%m%d-%H%M%S}-{direction}.sqlite"
    journal = Journal(journal_path)
    journal.add_plan(items, settings)
    if not args.json:
        print(tr("cli.batch.plan", n=len(journal.pending()), size=format_size(sum(i.size for i in journal.pending()))))
        if direction == "encode" and options.originals != "replace":
            needed = instant(inv, settings).projected_bytes
            target = options.mirror_dir or args.paths[0]
            if not check_free_space(Path(target), needed):
                print(tr("cli.batch.free_space", needed=format_size(needed)), file=sys.stderr)
    total = len(journal.pending())
    state = {"done": 0, "last": 0.0}

    def progress(result) -> None:
        state["done"] += 1
        if result.state == "failed":
            print(f"{tr('state.failed')} : {result.src} ({tr('reason.' + result.reason)})", file=sys.stderr)
        now = time.perf_counter()
        if not args.json and (now - state["last"] >= 1.0 or state["done"] == total):
            state["last"] = now
            print(tr("cli.batch.progress", done=state["done"], total=total), file=sys.stderr)

    summary = run(journal, settings, options, on_progress=progress)
    summary["journal"] = str(journal_path)
    journal.close()
    if args.json:
        _emit(summary)
    else:
        print(tr("cli.batch.summary", **{k: summary[k] for k in ("done", "skipped", "failed", "pending")}))
        before, after = summary["bytes_before"], summary["bytes_after"]
        pct = format_number(100.0 * (before - after) / before if before else 0.0, 1)
        print(tr("cli.batch.sizes", before=format_size(before), after=format_size(after), pct=pct))
        for reason, count in sorted(summary["reasons"].items()):
            state_key = "state.skipped" if reason in SKIP_REASONS | {"already_converted"} else "state.failed"
            print(f"  {tr(state_key)} : {count} ({tr('reason.' + reason)})")
        if summary["paused"]:
            print(tr("cli.batch.paused", reason=tr("reason." + summary["paused"])))
        print(tr("cli.batch.journal", path=journal_path))
    return EXIT_PARTIAL if summary["failed"] or summary["paused"] else EXIT_OK


def cmd_encode(args) -> int:
    return _batch(args, "encode", settings_from(args))


def cmd_decode(args) -> int:
    return _batch(args, "decode", EncodeSettings())


def _param_dict(spec) -> dict:
    return {
        "id": spec.id, "label": spec.label(), "tooltip": spec.tooltip(), "option": spec.cli_flag,
        "draco_option": spec.draco_flag, "type": spec.type, "default": spec.default_text(),
        "minimum": spec.minimum, "maximum": spec.maximum, "choices": spec.choices, "help": spec.help_sections(),
    }


def cmd_params(args) -> int:
    if args.name is None:
        if args.json:
            _emit({spec.id: _param_dict(spec) for spec in CATALOG.values()})
            return EXIT_OK
        for spec in CATALOG.values():
            print(f"{spec.cli_flag:<22}{spec.label()}")
            print(f"{'':<22}{spec.tooltip()}")
            print(f"{'':<22}{tr('help.default', value=spec.default_text())}")
        return EXIT_OK
    name = args.name.strip().lstrip("-").replace("-", "_")
    spec = CATALOG.get(name) or next((s for s in CATALOG.values() if s.cli_flag.lstrip("-").replace("-", "_") == name), None)
    if spec is None:
        raise UsageError(tr("cli.error.unknown_param", name=args.name))
    if args.json:
        _emit(_param_dict(spec))
        return EXIT_OK
    print(f"{spec.label()}  ({spec.cli_flag})")
    print(spec.tooltip())
    print(tr("help.default", value=spec.default_text()))
    if spec.minimum is not None:
        print(tr("help.range", minimum=spec.minimum, maximum=spec.maximum))
    if spec.draco_flag:
        print(tr("help.draco_flag", flag=spec.draco_flag))
    for section, text in spec.help_sections().items():
        print(f"\n{tr('help.section.' + section)}\n  {text}")
    return EXIT_OK


def cmd_gui(args) -> int:
    from .gui.app import main as gui_main

    return gui_main()


_COMMANDS = {
    "scan": cmd_scan, "estimate": cmd_estimate, "quality": cmd_quality, "encode": cmd_encode,
    "decode": cmd_decode, "params": cmd_params, "gui": cmd_gui,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    language = _language_from(argv)
    set_language(language if language in ("fr", "en") else system_language())
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except UsageError as exc:
        print(f"dracoconv: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"dracoconv: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return EXIT_PARTIAL


if __name__ == "__main__":
    sys.exit(main())
