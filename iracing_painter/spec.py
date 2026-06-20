"""Load and validate livery specs against the versioned contract.

Two layers of validation:
  1. Structural — JSON Schema (shape, required keys, color format, fill types).
  2. Semantic — things JSON Schema can't know: the template exists, and every
     referenced zone name is real for that template (from zones/labels.json).

`load_spec` returns (spec, template_dir, warnings). Hard problems raise SpecError
with a readable message; soft issues (e.g. unrendered features in v0.1) come back
as warnings so the caller can surface them without failing.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

SCHEMA_VERSION = "0.1"
_SCHEMA_PATH = Path(__file__).parent / "schemas" / f"livery-{SCHEMA_VERSION}.schema.json"


class SpecError(ValueError):
    """Raised when a livery spec is invalid."""


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def validate(spec: dict, templates_root: Path) -> tuple[Path, list[str]]:
    """Validate a spec dict. Returns (template_dir, warnings) or raises SpecError."""
    # 1. Structural.
    try:
        jsonschema.validate(spec, _load_schema())
    except jsonschema.ValidationError as e:
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise SpecError(f"schema error at {loc}: {e.message}") from None

    # 2. Semantic — template must exist and be extracted.
    template_dir = templates_root / spec["template"]
    if not template_dir.is_dir():
        raise SpecError(
            f"unknown template {spec['template']!r} (no dir {template_dir})"
        )
    if not (template_dir / "base.png").exists():
        raise SpecError(
            f"template {spec['template']!r} not extracted yet — run: "
            f"python -m iracing_painter.extract {template_dir}"
        )

    warnings: list[str] = []

    # 3. Semantic — referenced zone names must exist in the template's labels.
    labels_path = template_dir / "zones" / "labels.json"
    valid_targets: set[str] = set()
    if labels_path.exists():
        labels = json.loads(labels_path.read_text())
        valid_targets = set(labels.get("zones", {})) | set(labels.get("groups", {}))
    referenced = set(spec.get("zones", {})) | set(
        spec.get("materials", {}).get("zones", {})
    )
    if labels_path.exists():
        unknown = sorted(referenced - valid_targets)
        if unknown:
            raise SpecError(
                f"unknown zone/group {unknown} for template {spec['template']!r}. "
                f"Valid: {sorted(valid_targets)}"
            )
    elif referenced:
        warnings.append(
            f"template has no zones/labels.json yet; cannot verify zones {sorted(referenced)}"
        )

    # 4. Element semantics.
    implemented_elements = {"number", "logo"}
    elements = spec.get("elements", [])
    types = {e.get("type") for e in elements}
    for el in elements:
        if el.get("type") not in implemented_elements:
            warnings.append(f"element type {el.get('type')!r} not rendered yet")
    if "number" in types and not (template_dir / "number_blocks.json").exists():
        warnings.append("number element present but template has no number_blocks.json")

    # Logos: asset must exist; a zone anchor must be a real zone/group.
    logos = [e for e in elements if e.get("type") == "logo"]
    if logos:
        from .assets import LocalAssetProvider

        provider = LocalAssetProvider()
        for el in logos:
            if not provider.has(el["asset"]):
                raise SpecError(
                    f"unknown asset {el['asset']!r}; available: {provider.names()}"
                )
            if ("zone" in el) == ("at" in el):
                raise SpecError(
                    f"logo {el['asset']!r} needs exactly one of 'zone' or 'at' "
                    f"(got {'both' if 'zone' in el else 'neither'})"
                )
            if "zone" in el and labels_path.exists() and el["zone"] not in valid_targets:
                raise SpecError(
                    f"logo zone {el['zone']!r} not a valid zone/group. "
                    f"Valid: {sorted(valid_targets)}"
                )

    if spec.get("materials"):
        warnings.append("materials present but spec-map generation lands in P5")

    return template_dir, warnings


def load_spec(path: str | Path, templates_root: str | Path = "templates"):
    """Read, parse, and validate a spec file. Returns (spec, template_dir, warnings)."""
    path = Path(path)
    try:
        spec = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: invalid JSON — {e}") from None
    template_dir, warnings = validate(spec, Path(templates_root))
    return spec, template_dir, warnings


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "liveries/example.json"
    try:
        spec, template_dir, warnings = load_spec(target)
    except SpecError as e:
        print(f"INVALID: {e}")
        raise SystemExit(1)
    print(f"OK: {target}  (template: {spec['template']})")
    for w in warnings:
        print(f"  warning: {w}")
