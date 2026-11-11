"""Catalogue des paramètres d'encodage : source unique pour la fenêtre, la ligne de commande et l'aide."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .i18n import tr

HELP_SECTIONS = ("what", "size", "quality", "recommended", "orca")
MAX_BITS = 30
SKIPPABLE = ("normal", "texcoord", "color", "generic")


@dataclass(frozen=True)
class ParamSpec:
    id: str
    type: Literal["int", "float", "bool", "set"]
    default: Any
    cli_flag: str
    draco_flag: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None

    def label(self) -> str:
        return tr(f"param.{self.id}.label")

    def tooltip(self) -> str:
        return tr(f"param.{self.id}.tooltip")

    def help_sections(self) -> dict[str, str]:
        return {name: tr(f"param.{self.id}.help_{name}") for name in HELP_SECTIONS}

    def default_text(self) -> str:
        if self.type == "bool":
            return tr("value.yes") if self.default else tr("value.no")
        if self.type == "set":
            return ", ".join(tr(f"attr.{a}") for a in sorted(self.default)) or tr("value.none")
        if self.default is None:
            return tr("value.none")
        return str(self.default)


def _bits(pid: str, default: int, flag: str) -> ParamSpec:
    return ParamSpec(pid, "int", default, "--" + pid.replace("_", "-"), flag, 0, MAX_BITS)


_SPECS = (
    ParamSpec("compression_level", "int", 10, "--compression-level", "-cl", 0, 10),
    _bits("position_bits", 0, "-qp"),
    ParamSpec("tolerance_mm", "float", None, "--tolerance-mm", None, 1e-6, 10.0),
    _bits("texcoord_bits", 10, "-qt"),
    _bits("normal_bits", 8, "-qn"),
    _bits("generic_bits", 8, "-qg"),
    ParamSpec("skip_attributes", "set", frozenset({"normal"}), "--skip", "--skip", choices=SKIPPABLE),
    ParamSpec("point_cloud", "bool", False, "--point-cloud", "-point_cloud"),
    ParamSpec("preserve_order", "bool", False, "--preserve-order", None),
    ParamSpec("metadata", "bool", False, "--metadata", "--metadata"),
    ParamSpec("preserve_polygons", "bool", False, "--preserve-polygons", "-preserve_polygons"),
)

CATALOG: dict[str, ParamSpec] = {spec.id: spec for spec in _SPECS}
