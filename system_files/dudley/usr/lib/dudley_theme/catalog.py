"""Strict loading and discovery for Dudley theme catalogs."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


CATALOG_SCHEMA_VERSION = 2
PROVENANCE_SCHEMA_VERSION = 1
RENDERER_VERSION = 1
KNOWN_ADAPTER_IDS = frozenset(
    {
        "btop",
        "ghostty",
        "gnome",
        "kitty",
        "neovim",
        "vscode",
    }
)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_THEME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PROVENANCE_FIELDS = (
    "source",
    "author",
    "license",
    "original_sha256",
    "shipped_sha256",
    "modification_status",
    "required_attribution",
)


class ThemeCatalogError(ValueError):
    """Raised when an installed theme violates the catalog contract."""


@dataclass(frozen=True)
class ProvenanceRecord:
    path: str
    source: str
    author: str
    license: str
    original_sha256: str
    shipped_sha256: str
    modification_status: str
    required_attribution: str
    generation: Mapping[str, str]


@dataclass(frozen=True)
class RenderOutput:
    path: str
    source: str


@dataclass(frozen=True)
class ThemeManifest:
    root: Path
    manifest: Mapping[str, Any]
    colors: Mapping[str, str]
    provenance: Mapping[str, ProvenanceRecord]
    render_outputs: tuple[RenderOutput, ...]
    required_adapters: tuple[str, ...]
    optional_adapters: tuple[str, ...]

    @property
    def id(self) -> str:
        return str(self.manifest["id"])

    @property
    def name(self) -> str:
        return str(self.manifest["name"])

    @property
    def version(self) -> str:
        return str(self.manifest["version"])


def load_theme(path: Path) -> ThemeManifest:
    """Load one schema-v2 theme after validating every shipped input."""
    root = Path(path)
    if not root.is_dir():
        raise ThemeCatalogError(f"theme directory does not exist: {root}")
    root = root.resolve()

    manifest_path = root / "manifest.json"
    manifest = _read_json_object(manifest_path, "theme manifest")
    schema_version = manifest.get("schema_version")
    if schema_version != CATALOG_SCHEMA_VERSION:
        raise ThemeCatalogError(
            f"unsupported theme schema version {schema_version!r}; "
            f"expected {CATALOG_SCHEMA_VERSION}"
        )

    theme_id = _required_string(manifest, "id", "theme manifest")
    if not _THEME_ID_PATTERN.fullmatch(theme_id):
        raise ThemeCatalogError(f"invalid theme id: {theme_id!r}")
    _required_string(manifest, "name", "theme manifest")
    _required_string(manifest, "version", "theme manifest")

    colors_name = _required_string(manifest, "colors", "theme manifest")
    if colors_name != "colors.toml":
        raise ThemeCatalogError("schema-v2 theme manifest colors must be 'colors.toml'")
    if (root / "colors.toml").exists() and (root / "palette.toml").exists():
        raise ThemeCatalogError("theme contains both palette.toml and colors.toml")
    colors_path = _declared_file(root, colors_name, "colors")
    colors = _read_colors(colors_path)

    provenance_name = _required_string(manifest, "provenance", "theme manifest")
    if provenance_name != "provenance.json":
        raise ThemeCatalogError(
            "schema-v2 theme manifest provenance must be 'provenance.json'"
        )
    provenance_path = _declared_file(root, provenance_name, "provenance")

    required_adapters, optional_adapters = _read_adapter_profiles(manifest)
    render_outputs = _read_render_outputs(root, manifest)
    declared_paths = _declared_asset_paths(manifest)
    declared_paths.add(colors_name)
    declared_paths.update(output.source for output in render_outputs)
    for relative_path in sorted(declared_paths):
        _declared_file(root, relative_path, "declared")

    provenance = _read_provenance(
        root,
        provenance_path,
        theme_id=theme_id,
    )

    return ThemeManifest(
        root=root,
        manifest=MappingProxyType(dict(manifest)),
        colors=MappingProxyType(colors),
        provenance=MappingProxyType(provenance),
        render_outputs=render_outputs,
        required_adapters=required_adapters,
        optional_adapters=optional_adapters,
    )


def discover_themes(path: Path) -> dict[str, ThemeManifest]:
    """Return installed themes in deterministic theme-ID order."""
    catalog_root = Path(path)
    if not catalog_root.exists():
        return {}
    if not catalog_root.is_dir():
        raise ThemeCatalogError(
            f"theme catalog path is not a directory: {catalog_root}"
        )

    discovered: dict[str, ThemeManifest] = {}
    for candidate in sorted(catalog_root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or not (candidate / "manifest.json").is_file():
            continue
        theme = load_theme(candidate)
        if theme.id in discovered:
            raise ThemeCatalogError(f"duplicate theme id: {theme.id}")
        discovered[theme.id] = theme
    return dict(sorted(discovered.items()))


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ThemeCatalogError(f"missing {label}: {path}") from error
    except OSError as error:
        raise ThemeCatalogError(f"cannot read {label}: {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ThemeCatalogError(f"invalid JSON in {label}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ThemeCatalogError(f"{label} must contain a JSON object: {path}")
    return value


def _read_colors(path: Path) -> dict[str, str]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ThemeCatalogError(f"cannot read colors: {path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ThemeCatalogError(f"invalid colors TOML: {path}: {error}") from error
    colors: dict[str, str] = {}
    for key, color in value.items():
        if not isinstance(key, str) or not isinstance(color, str):
            raise ThemeCatalogError(
                f"colors.toml tokens must be string values: {key!r}"
            )
        colors[key] = color
    if not colors:
        raise ThemeCatalogError("colors.toml must define at least one token")
    return colors


def _read_adapter_profiles(
    manifest: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    profiles = manifest.get("fidelity_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ThemeCatalogError(
            "theme manifest fidelity_profiles must be a non-empty object"
        )

    required: list[str] = []
    optional: list[str] = []
    for profile_name in sorted(profiles):
        profile = profiles[profile_name]
        if not isinstance(profile_name, str) or not profile_name:
            raise ThemeCatalogError("fidelity profile names must be non-empty")
        if not isinstance(profile, dict):
            raise ThemeCatalogError(
                f"fidelity profile {profile_name!r} must be an object"
            )
        profile_required = _adapter_list(
            profile.get("required_adapters"),
            f"fidelity profile {profile_name!r} required_adapters",
        )
        profile_optional = _adapter_list(
            profile.get("optional_adapters", []),
            f"fidelity profile {profile_name!r} optional_adapters",
        )
        unknown = sorted(set(profile_required) - KNOWN_ADAPTER_IDS)
        if unknown:
            raise ThemeCatalogError(
                "unknown required adapter IDs: " + ", ".join(unknown)
            )
        overlap = sorted(set(profile_required) & set(profile_optional))
        if overlap:
            raise ThemeCatalogError(
                f"adapters cannot be required and optional in "
                f"{profile_name!r}: {', '.join(overlap)}"
            )
        required.extend(profile_required)
        optional.extend(profile_optional)

    return _unique(required), _unique(optional)


def _adapter_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ThemeCatalogError(f"{label} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ThemeCatalogError(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ThemeCatalogError(f"{label} contains duplicate adapter IDs")
    return list(value)


def _read_render_outputs(
    root: Path, manifest: Mapping[str, Any]
) -> tuple[RenderOutput, ...]:
    render = manifest.get("render")
    if not isinstance(render, dict):
        raise ThemeCatalogError("theme manifest render must be an object")
    if render.get("version") != RENDERER_VERSION:
        raise ThemeCatalogError(
            f"unsupported renderer version {render.get('version')!r}; "
            f"expected {RENDERER_VERSION}"
        )
    outputs = render.get("outputs")
    if not isinstance(outputs, list):
        raise ThemeCatalogError("theme manifest render.outputs must be an array")

    result: list[RenderOutput] = []
    seen: set[str] = set()
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            raise ThemeCatalogError(f"render output {index} must be an object")
        output_path = _safe_relative_path(output.get("path"), "render output path")
        source_path = _safe_relative_path(output.get("source"), "render source path")
        if output_path in seen:
            raise ThemeCatalogError(f"duplicate render output path: {output_path}")
        seen.add(output_path)
        _declared_file(root, source_path, "render source")
        result.append(RenderOutput(path=output_path, source=source_path))
    return tuple(sorted(result, key=lambda output: output.path))


def _declared_asset_paths(manifest: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        raise ThemeCatalogError("theme manifest assets must be an object")
    _collect_asset_paths(assets, result)

    gnome = manifest.get("gnome")
    if gnome is not None:
        if not isinstance(gnome, dict):
            raise ThemeCatalogError("theme manifest gnome must be an object")
        if "dconf" in gnome:
            result.add(_safe_relative_path(gnome["dconf"], "GNOME dconf path"))
    return result


def _collect_asset_paths(value: Any, result: set[str]) -> None:
    if isinstance(value, str):
        result.add(_safe_relative_path(value, "asset path"))
        return
    if isinstance(value, list):
        for item in value:
            _collect_asset_paths(item, result)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_asset_paths(item, result)
        return
    raise ThemeCatalogError("theme manifest asset values must be paths or arrays")


def _read_provenance(
    root: Path,
    path: Path,
    *,
    theme_id: str,
) -> dict[str, ProvenanceRecord]:
    document = _read_json_object(path, "provenance")
    if document.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        raise ThemeCatalogError(
            "unsupported provenance schema version "
            f"{document.get('schema_version')!r}; "
            f"expected {PROVENANCE_SCHEMA_VERSION}"
        )
    if document.get("theme_id") != theme_id:
        raise ThemeCatalogError("provenance theme_id does not match theme manifest")
    raw_records = document.get("records")
    if not isinstance(raw_records, dict):
        raise ThemeCatalogError("provenance records must be an object")

    records: dict[str, ProvenanceRecord] = {}
    for raw_path, raw_record in sorted(raw_records.items()):
        relative_path = _safe_relative_path(raw_path, "provenance path")
        if not isinstance(raw_record, dict):
            raise ThemeCatalogError(
                f"provenance record must be an object: {relative_path}"
            )
        values = {
            field: _required_string(
                raw_record,
                field,
                f"provenance record {relative_path!r}",
            )
            for field in _PROVENANCE_FIELDS
        }
        for hash_field in ("original_sha256", "shipped_sha256"):
            if not _HASH_PATTERN.fullmatch(values[hash_field]):
                raise ThemeCatalogError(
                    f"invalid {hash_field} in provenance: {relative_path}"
                )
        generation = raw_record.get("generation", {})
        if not isinstance(generation, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in generation.items()
        ):
            raise ThemeCatalogError(
                f"provenance generation must contain string fields: {relative_path}"
            )

        asset_path = _declared_file(root, relative_path, "provenance asset")
        actual_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        if actual_hash != values["shipped_sha256"]:
            raise ThemeCatalogError(
                f"shipped hash mismatch for provenance asset: {relative_path}"
            )
        records[relative_path] = ProvenanceRecord(
            path=relative_path,
            source=values["source"],
            author=values["author"],
            license=values["license"],
            original_sha256=values["original_sha256"],
            shipped_sha256=values["shipped_sha256"],
            modification_status=values["modification_status"],
            required_attribution=values["required_attribution"],
            generation=MappingProxyType(dict(generation)),
        )

    shipped_paths = {
        str(candidate.relative_to(root))
        for candidate in root.rglob("*")
        if candidate.is_file()
        and candidate.name not in {"manifest.json", "provenance.json"}
    }
    missing = sorted(shipped_paths - records.keys())
    if missing:
        raise ThemeCatalogError(
            "missing provenance records for assets: " + ", ".join(missing)
        )
    extra = sorted(records.keys() - shipped_paths)
    if extra:
        raise ThemeCatalogError(
            "provenance records reference unshipped assets: " + ", ".join(extra)
        )
    return records


def _declared_file(root: Path, value: Any, label: str) -> Path:
    relative_path = _safe_relative_path(value, f"{label} path")
    candidate = root / relative_path
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise ThemeCatalogError(f"missing declared file: {relative_path}") from error
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ThemeCatalogError(
            f"{label} path is not a file inside the theme: {relative_path}"
        )
    return resolved


def _safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ThemeCatalogError(f"{label} must be a non-empty string")
    if "\\" in value:
        raise ThemeCatalogError(f"unsafe {label}: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ThemeCatalogError(f"unsafe {label}: {value!r}")
    return path.as_posix()


def _required_string(
    value: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ThemeCatalogError(f"{label} field {key!r} must be a non-empty string")
    return result


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
