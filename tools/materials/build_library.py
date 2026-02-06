"""tools/materials/build_library.py

Build or update the project material library (.blend) from Python specs.

Usage (from repo root):
  blender -b --factory-startup --python tools/materials/build_library.py -- \
    --library assets/library/materials/materials.blend \
    --catalog assets/library/materials/materials_catalog.json

Optional:
  --recipes tools/materials/material_recipes.py
  --pack          # pack external data into the library (usually not required)
  --force-new     # ignore existing library and start fresh

This script is intended to be deterministic and version-control friendly:
- materials are created/updated by stable name
- a JSON catalog is written for easy review and for use in ChatGPT prompts
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import bpy


def repo_root() -> Path:
    # tools/materials/build_library.py -> materials -> tools -> repo root
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(p: str) -> Path:
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return (repo_root() / pp).resolve()


def argv_after_dashes() -> List[str]:
    import sys
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build/update material library .blend")

    p.add_argument(
        "--library",
        default="assets/library/materials/materials.blend",
        help="Output .blend path for the material library",
    )
    p.add_argument(
        "--recipes",
        default="tools/materials/material_recipes.py",
        help="Python file defining MATERIAL_SPECS and create_or_update_all_materials()",
    )
    p.add_argument(
        "--catalog",
        default="assets/library/materials/materials_catalog.json",
        help="Output JSON catalog of materials (names/specs) for tooling and prompts",
    )
    p.add_argument("--pack", action="store_true", help="Pack external resources into the library .blend")
    p.add_argument("--force-new", action="store_true", help="Start from a clean file even if library exists")

    return p.parse_args(argv_after_dashes())


def import_recipes_module(recipes_path: Path):
    spec = importlib.util.spec_from_file_location("material_recipes", str(recipes_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import recipes module at {recipes_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean_scene() -> None:
    # Remove all objects in the file (library doesn't need them)
    for obj in list(bpy.data.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    # Optionally remove collections except master
    for col in list(bpy.data.collections):
        if col.users == 0:
            try:
                bpy.data.collections.remove(col)
            except Exception:
                pass


def write_catalog(catalog_path: Path, recipes_mod) -> None:
    mats = sorted([m.name for m in bpy.data.materials])

    data: Dict[str, Any] = {
        "library_blend": "assets/library/materials/materials.blend",
        "materials_in_file": mats,
        "material_specs": getattr(recipes_mod, "MATERIAL_SPECS", {}),
    }

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"[build_library] Wrote catalog: {catalog_path}")


def main() -> None:
    args = parse_args()

    library_path = resolve_repo_path(args.library)
    recipes_path = resolve_repo_path(args.recipes)
    catalog_path = resolve_repo_path(args.catalog)

    print(f"[build_library] repo_root = {repo_root()}")
    print(f"[build_library] library  = {library_path}")
    print(f"[build_library] recipes  = {recipes_path}")
    print(f"[build_library] catalog  = {catalog_path}")

    # Open existing library if present (unless force-new)
    if (not args.force_new) and library_path.exists():
        print("[build_library] Opening existing library file to update...")
        bpy.ops.wm.open_mainfile(filepath=str(library_path))
    else:
        print("[build_library] Starting from clean factory-startup file...")
        clean_scene()

    recipes_mod = import_recipes_module(recipes_path)

    if not hasattr(recipes_mod, "create_or_update_all_materials"):
        raise RuntimeError(
            f"Recipes module {recipes_path} must define create_or_update_all_materials()"
        )

    mats = recipes_mod.create_or_update_all_materials()
    print(f"[build_library] Created/updated {len(mats)} materials:")
    for m in mats:
        print(f"  - {m.name}")

    if args.pack:
        try:
            bpy.ops.file.pack_all()
            print("[build_library] Packed external resources into the library.")
        except Exception as e:
            print(f"[build_library] WARN: pack_all failed: {e!r}")

    # Save library .blend
    library_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(library_path), check_existing=False, compress=True)
    print(f"[build_library] Saved library: {library_path}")

    # Write catalog JSON (text, commit-friendly)
    write_catalog(catalog_path, recipes_mod)


if __name__ == "__main__":
    main()
