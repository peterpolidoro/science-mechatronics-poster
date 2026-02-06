"""tools/materials/sync_to_asset.py

Hybrid workflow helper:
- LINK mode: Link materials from the material library into an asset .blend (development stage).
- BAKE mode: Make linked materials (and their common dependencies) local, and optionally pack resources
             into the asset .blend (compiled stage).

Usage (from repo root):

  # 1) Link library materials into a dev asset (keeps live link to library)
  blender -b --factory-startup --python tools/materials/sync_to_asset.py -- \
    --mode link \
    --asset assets/src/blend/joystick_dev.blend \
    --library assets/library/materials/materials.blend \
    --materials "MAT_*"

  # 2) Bake dev asset to compiled asset (no external library dependencies; packed)
  blender -b --factory-startup --python tools/materials/sync_to_asset.py -- \
    --mode bake \
    --asset assets/src/blend/joystick_dev.blend \
    --out assets/compiled/blend/joystick.blend \
    --pack

Notes:
- In LINK mode, adding *new* materials later requires running LINK again (to bring the new datablocks in).
  Changes to existing linked materials automatically propagate when you open the asset/poster.
- In BAKE mode, this script tries to remove *library* dependencies by copying linked datablocks locally.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import bpy


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(p: str) -> Path:
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return (repo_root() / pp).resolve()


def argv_after_dashes() -> List[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Link/bake material library into asset .blend")

    p.add_argument("--mode", choices=["link", "bake", "link_then_bake"], required=True)
    p.add_argument("--asset", required=True, help="Input asset .blend file to modify")
    p.add_argument("--out", default=None, help="Output .blend path (default: overwrite asset)")
    p.add_argument(
        "--library",
        default="assets/library/materials/materials.blend",
        help="Material library .blend path (used for LINK mode; optional for BAKE)",
    )
    p.add_argument(
        "--materials",
        action="append",
        default=[],
        help='Material name glob pattern to link (repeatable). Default: "MAT_*"',
    )

    # Bake options
    p.add_argument("--pack", action="store_true", help="Pack external resources into the output asset .blend")
    p.add_argument("--no-pack", action="store_true", help="Disable packing (overrides --pack)")
    p.add_argument("--bake-used-only", action="store_true", help="Bake only linked materials that are used")

    return p.parse_args(argv_after_dashes())


def _make_paths_relative() -> None:
    # Best-effort relative paths for images and other filepaths
    try:
        bpy.ops.file.make_paths_relative()
    except Exception:
        pass


def _link_materials_from_library(library_path: Path, patterns: List[str]) -> List[str]:
    """Link materials matching patterns from library into current file. Returns names linked/ensured."""
    if not patterns:
        patterns = ["MAT_*"]

    lib = str(library_path)
    if not library_path.exists():
        raise FileNotFoundError(f"Material library not found: {library_path}")

    already = {m.name for m in bpy.data.materials}

    linked: List[str] = []
    with bpy.data.libraries.load(lib, link=True) as (data_from, data_to):
        available = list(getattr(data_from, "materials", []))
        want: List[str] = []
        for nm in available:
            if any(fnmatch.fnmatch(nm, pat) for pat in patterns):
                # Avoid duplicating by name; load only missing
                if nm not in already:
                    want.append(nm)
                else:
                    linked.append(nm)  # already present (maybe previously linked)
        data_to.materials = want

    # Mark as fake user so they remain in file even if not assigned yet
    for nm in linked:
        mat = bpy.data.materials.get(nm)
        if mat is None:
            continue
        try:
            mat.use_fake_user = True
        except Exception:
            pass

    # Any newly linked materials are now in bpy.data.materials
    for mat in bpy.data.materials:
        if mat.name not in already and any(fnmatch.fnmatch(mat.name, pat) for pat in patterns):
            linked.append(mat.name)
            try:
                mat.use_fake_user = True
            except Exception:
                pass

    linked = sorted(set(linked))
    print(f"[sync_to_asset] Linked/ensured {len(linked)} materials from library.")
    return linked


def _iter_node_trees() -> Iterable[bpy.types.NodeTree]:
    """Yield node trees where linked images/nodegroups may appear."""
    for m in bpy.data.materials:
        if m and m.use_nodes and m.node_tree:
            yield m.node_tree
    for ng in bpy.data.node_groups:
        if ng and ng.nodes:
            yield ng
    # World(s)
    for w in bpy.data.worlds:
        if w and w.use_nodes and w.node_tree:
            yield w.node_tree


def _bake_linked_images() -> int:
    linked = [img for img in bpy.data.images if getattr(img, "library", None) is not None]
    if not linked:
        return 0

    mapping: Dict[bpy.types.Image, bpy.types.Image] = {}
    for img in linked:
        try:
            new_img = img.copy()
            new_img.name = img.name + "__LOCAL_TMP"
            mapping[img] = new_img
        except Exception as e:
            print(f"[sync_to_asset] WARN: Could not copy image {img.name}: {e!r}")

    # Replace image references in nodes
    for nt in _iter_node_trees():
        for node in nt.nodes:
            if hasattr(node, "image") and node.image in mapping:
                node.image = mapping[node.image]

    # Rename + remove old
    for old, new in mapping.items():
        old_name = old.name
        try:
            old.name = old_name + "__LINKED"
        except Exception:
            pass
        try:
            new.name = old_name
        except Exception:
            pass
        try:
            if old.users == 0:
                bpy.data.images.remove(old)
        except Exception:
            pass

    return len(mapping)


def _bake_linked_node_groups() -> int:
    linked = [ng for ng in bpy.data.node_groups if getattr(ng, "library", None) is not None]
    if not linked:
        return 0

    mapping: Dict[bpy.types.NodeTree, bpy.types.NodeTree] = {}
    for ng in linked:
        try:
            new_ng = ng.copy()
            new_ng.name = ng.name + "__LOCAL_TMP"
            mapping[ng] = new_ng
        except Exception as e:
            print(f"[sync_to_asset] WARN: Could not copy node group {ng.name}: {e!r}")

    # Replace group-node references
    for nt in _iter_node_trees():
        for node in nt.nodes:
            if getattr(node, "type", None) == "GROUP" and getattr(node, "node_tree", None) in mapping:
                node.node_tree = mapping[node.node_tree]

    # Rename + remove old
    for old, new in mapping.items():
        old_name = old.name
        try:
            old.name = old_name + "__LINKED"
        except Exception:
            pass
        try:
            new.name = old_name
        except Exception:
            pass
        try:
            if old.users == 0:
                bpy.data.node_groups.remove(old)
        except Exception:
            pass

    return len(mapping)


def _bake_linked_materials(used_only: bool) -> int:
    linked = [m for m in bpy.data.materials if getattr(m, "library", None) is not None]
    if used_only:
        linked = [m for m in linked if m.users > 0]

    if not linked:
        return 0

    mapping: Dict[bpy.types.Material, bpy.types.Material] = {}
    for m in linked:
        try:
            new_m = m.copy()
            new_m.name = m.name + "__LOCAL_TMP"
            mapping[m] = new_m
        except Exception as e:
            print(f"[sync_to_asset] WARN: Could not copy material {m.name}: {e!r}")

    # Replace object material slots
    for obj in bpy.data.objects:
        try:
            if not hasattr(obj, "material_slots"):
                continue
            for slot in obj.material_slots:
                if slot.material in mapping:
                    slot.material = mapping[slot.material]
        except Exception:
            pass

    # Rename + remove old
    for old, new in mapping.items():
        old_name = old.name
        try:
            old.name = old_name + "__LINKED"
        except Exception:
            pass
        try:
            new.name = old_name
        except Exception:
            pass
        try:
            if old.users == 0:
                bpy.data.materials.remove(old)
        except Exception:
            pass

    return len(mapping)


def _report_remaining_linked() -> None:
    mats = [m.name for m in bpy.data.materials if getattr(m, "library", None) is not None]
    ngs = [ng.name for ng in bpy.data.node_groups if getattr(ng, "library", None) is not None]
    imgs = [im.name for im in bpy.data.images if getattr(im, "library", None) is not None]
    libs = {getattr(idb.library, "filepath", None) for idb in (list(bpy.data.materials) + list(bpy.data.node_groups) + list(bpy.data.images)) if getattr(idb, "library", None) is not None}

    libs = sorted([x for x in libs if x])
    print(f"[sync_to_asset] Remaining linked datablocks: materials={len(mats)} node_groups={len(ngs)} images={len(imgs)}")
    if libs:
        print("[sync_to_asset] Remaining libraries referenced:")
        for l in libs:
            print(f"  - {l}")


def _pack_all() -> None:
    try:
        bpy.ops.file.pack_all()
        print("[sync_to_asset] Packed external resources into the output asset.")
    except Exception as e:
        print(f"[sync_to_asset] WARN: pack_all failed: {e!r}")


def main() -> None:
    args = parse_args()

    asset_path = resolve_repo_path(args.asset)
    out_path = resolve_repo_path(args.out) if args.out else asset_path
    library_path = resolve_repo_path(args.library)

    patterns = args.materials[:] if args.materials else ["MAT_*"]

    print(f"[sync_to_asset] repo_root = {repo_root()}")
    print(f"[sync_to_asset] mode      = {args.mode}")
    print(f"[sync_to_asset] asset     = {asset_path}")
    print(f"[sync_to_asset] out       = {out_path}")
    if args.mode in ("link", "link_then_bake"):
        print(f"[sync_to_asset] library   = {library_path}")
        print(f"[sync_to_asset] patterns  = {patterns}")

    if not asset_path.exists():
        raise FileNotFoundError(f"Asset .blend not found: {asset_path}")

    bpy.ops.wm.open_mainfile(filepath=str(asset_path))

    # Prefer relative paths in saved files
    try:
        bpy.context.preferences.filepaths.use_relative_paths = True
    except Exception:
        pass

    if args.mode in ("link", "link_then_bake"):
        _link_materials_from_library(library_path, patterns)
        _make_paths_relative()

    if args.mode in ("bake", "link_then_bake"):
        used_only = bool(args.bake_used_only)
        n_mat = _bake_linked_materials(used_only=used_only)
        # After materials are local, bake their dependencies too.
        n_ng = _bake_linked_node_groups()
        n_img = _bake_linked_images()

        print(f"[sync_to_asset] Baked to local copies: materials={n_mat} node_groups={n_ng} images={n_img}")

        # Pack if requested (default is pack unless explicitly disabled)
        pack = bool(args.pack) and (not args.no_pack)
        if pack and (not args.no_pack):
            _pack_all()
        _make_paths_relative()

        _report_remaining_linked()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path), check_existing=False, compress=True)
    print(f"[sync_to_asset] Saved: {out_path}")


if __name__ == "__main__":
    main()
