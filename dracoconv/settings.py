"""Réglages d'une conversion et profils."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace

from .config import config_dir
from .params import CATALOG
from .quality import bits_for_tolerance


@dataclass(frozen=True)
class EncodeSettings:
    compression_level: int = 10
    position_bits: int = 0
    tolerance_mm: float | None = None
    texcoord_bits: int = 10
    normal_bits: int = 8
    generic_bits: int = 8
    skip_attributes: frozenset[str] = frozenset({"normal"})
    point_cloud: bool = False
    preserve_order: bool = False
    keep_topology: bool = True
    metadata: bool = False
    preserve_polygons: bool = False

    def validate(self) -> None:
        for spec in CATALOG.values():
            value = getattr(self, spec.id)
            if spec.type in ("int", "float"):
                if value is None:
                    if spec.default is not None:
                        raise ValueError(f"{spec.id} : valeur requise")
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{spec.id} : nombre attendu")
                if spec.type == "int" and int(value) != value:
                    raise ValueError(f"{spec.id} : entier attendu")
                if not spec.minimum <= value <= spec.maximum:
                    raise ValueError(f"{spec.id} : {value} hors de [{spec.minimum}, {spec.maximum}]")
            elif spec.type == "bool":
                if not isinstance(value, bool):
                    raise ValueError(f"{spec.id} : oui ou non attendu")
            elif spec.type == "set":
                unknown = set(value) - set(spec.choices)
                if unknown:
                    raise ValueError(f"{spec.id} : valeurs inconnues {sorted(unknown)}")

    def to_json(self) -> str:
        data = asdict(self)
        data["skip_attributes"] = sorted(self.skip_attributes)
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "EncodeSettings":
        data = json.loads(text)
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known}
        if "skip_attributes" in data:
            data["skip_attributes"] = frozenset(data["skip_attributes"])
        settings = cls(**data)
        settings.validate()
        return settings

    def non_default(self) -> set[str]:
        """Identifiants des paramètres dont la valeur diffère du défaut."""
        return {spec.id for spec in CATALOG.values() if getattr(self, spec.id) != spec.default}


PROFILES: dict[str, EncodeSettings] = {
    "lossless": EncodeSettings(),
    "tolerance": EncodeSettings(tolerance_mm=0.001),
    "fixed_bits": EncodeSettings(position_bits=16),
    "orca": EncodeSettings(),
}


def resolve_bits(settings: EncodeSettings, max_extent: float) -> int:
    """Nombre de bits de position réellement appliqué à un modèle de cette taille."""
    if settings.tolerance_mm is not None:
        return bits_for_tolerance(max_extent, settings.tolerance_mm)
    return settings.position_bits


def resolved(settings: EncodeSettings, max_extent: float) -> EncodeSettings:
    """Réglages où la tolérance est remplacée par le nombre de bits qu'elle implique."""
    if settings.tolerance_mm is None:
        return settings
    return replace(settings, position_bits=resolve_bits(settings, max_extent), tolerance_mm=None)


def _profiles_file():
    return config_dir() / "profiles.json"


def user_profiles() -> dict[str, EncodeSettings]:
    path = _profiles_file()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: EncodeSettings.from_json(json.dumps(data)) for name, data in raw.items()}


def _write_profiles(profiles: dict[str, EncodeSettings]) -> None:
    raw = {name: json.loads(s.to_json()) for name, s in profiles.items()}
    _profiles_file().write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def save_profile(name: str, settings: EncodeSettings) -> None:
    name = name.strip()
    if not name or name in PROFILES:
        raise ValueError(f"nom de profil réservé ou vide : {name!r}")
    settings.validate()
    profiles = user_profiles()
    profiles[name] = settings
    _write_profiles(profiles)


def delete_profile(name: str) -> None:
    profiles = user_profiles()
    profiles.pop(name, None)
    _write_profiles(profiles)
