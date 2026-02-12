"""assets/build/electrical_mechanical/build.py

Build an "electrical-mechanical corner" asset .blend from a JSON manifest.

The asset coordinate system:
- (0,0,0) is the corner.
- XZ plane (Y=0) is the LEFT wall.
- YZ plane (X=0) is the RIGHT wall.
- XY plane (Z=0) is the floor.
- With a camera placed in the (+1,+1,+1) direction looking at the origin:
  +Z appears UP, +X projects down-left, +Y projects down-right.

Usage (headless build):
  blender -b --factory-startup --python assets/build/electrical_mechanical/build.py -- \
    assets/build/electrical_mechanical/manifest.json

The builder saves the output .blend path defined by manifest["output"]["blend_path"].
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import bpy
from mathutils import Euler, Vector


# ----------------------------
# CLI helpers
# ----------------------------

def argv_after_dashes() -> List[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build an electrical-mechanical corner .blend from a JSON manifest"
    )
    p.add_argument(
        "manifest",
        nargs="?",
        default=None,
        help="Path to manifest.json (defaults to the manifest.json next to this script)",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Override output .blend filepath (otherwise uses manifest.output.blend_path)",
    )
    return p.parse_args(list(argv))


# ----------------------------
# Repo + path resolution
# ----------------------------

def find_repo_root(start: Path) -> Path:
    """Find repo root by walking upward looking for Makefile + poster/."""
    start = start.resolve()
    for p in [start] + list(start.parents):
        if (p / "Makefile").exists() and (p / "poster").is_dir():
            return p
    return start.parents[0]


def resolve_path(manifest_path: Path, maybe_rel: str | Path) -> str:
    """Resolve paths referenced by manifests.

    Strategy:
    - Absolute paths are returned as-is.
    - Try relative to the manifest directory.
    - Try relative to the repo root.
    - Finally, try each ancestor of the manifest directory.

    This is more flexible than poster/blendlib.py's resolver because our manifests
    live under assets/build/..., not poster/.
    """
    p = Path(maybe_rel)
    if p.is_absolute():
        return str(p)

    mp = manifest_path.resolve()
    manifest_dir = mp.parent

    cand = (manifest_dir / p).resolve()
    if cand.exists():
        return str(cand)

    repo_root = find_repo_root(manifest_dir)
    cand2 = (repo_root / p).resolve()
    if cand2.exists():
        return str(cand2)

    for anc in manifest_dir.parents:
        cand3 = (anc / p).resolve()
        if cand3.exists():
            return str(cand3)

    # Best-effort fallback (useful for error messages)
    return str(cand2)


# ----------------------------
# Import poster/blendlib utilities
# ----------------------------

REPO_ROOT = find_repo_root(Path(__file__).resolve())
POSTER_DIR = REPO_ROOT / "poster"
if str(POSTER_DIR) not in sys.path:
    sys.path.insert(0, str(POSTER_DIR))

# Reuse the project's battle-tested collection + material helpers.
from blendlib import (  # type: ignore
    apply_units,
    apply_world_settings,
    ensure_camera,
    ensure_child_collection,
    ensure_collection,
    ensure_empty,
    ensure_material_principled,
    load_collection_from_blend,
    move_object_to_collection,
    remove_startup_objects,
    set_world_transform,
)


# ----------------------------
# Blender helpers
# ----------------------------

def ensure_addon_enabled(module: str) -> None:
    try:
        bpy.ops.preferences.addon_enable(module=module)
    except Exception:
        pass


def ensure_track_to(
    obj: bpy.types.Object,
    target: bpy.types.Object,
    *,
    track_axis: str = "TRACK_NEGATIVE_Z",
    up_axis: str = "UP_Y",
) -> None:
    c = None
    for cc in obj.constraints:
        if cc.type == "TRACK_TO":
            c = cc
            break
    if c is None:
        c = obj.constraints.new(type="TRACK_TO")
    c.target = target
    try:
        c.track_axis = track_axis
    except Exception:
        c.track_axis = "TRACK_NEGATIVE_Z"
    try:
        c.up_axis = up_axis
    except Exception:
        c.up_axis = "UP_Y"


def coerce_scale(scale: Any) -> Tuple[float, float, float]:
    """Accept either scalar scale or [sx,sy,sz]."""
    if isinstance(scale, (int, float)):
        s = float(scale)
        return (s, s, s)
    if isinstance(scale, (list, tuple)) and len(scale) == 3:
        return (float(scale[0]), float(scale[1]), float(scale[2]))
    return (1.0, 1.0, 1.0)


def bbox_world(objs: Iterable[bpy.types.Object]) -> Tuple[Vector, Vector]:
    """World-space AABB for a set of objects, using their bound_box."""
    inf = 1.0e30
    vmin = Vector((inf, inf, inf))
    vmax = Vector((-inf, -inf, -inf))

    any_obj = False
    for obj in objs:
        if obj.type in {"EMPTY", "CAMERA", "LIGHT"}:
            continue
        try:
            bb = obj.bound_box
        except Exception:
            continue
        if not bb:
            continue
        any_obj = True
        mw = obj.matrix_world
        for corner in bb:
            v = mw @ Vector(corner)
            vmin.x = min(vmin.x, v.x)
            vmin.y = min(vmin.y, v.y)
            vmin.z = min(vmin.z, v.z)
            vmax.x = max(vmax.x, v.x)
            vmax.y = max(vmax.y, v.y)
            vmax.z = max(vmax.z, v.z)

    if not any_obj:
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))

    return vmin, vmax


def delete_collection_recursive(coll: bpy.types.Collection) -> None:
    """Delete a collection, its child collections, and objects in it.

    Warning: Only call on collections you *own* (local to this file).
    """
    for child in list(coll.children):
        delete_collection_recursive(child)

    for obj in list(coll.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass

    # Unlink from scene root if present
    try:
        if bpy.context.scene.collection.children.get(coll.name):
            bpy.context.scene.collection.children.unlink(coll)
    except Exception:
        pass

    # Unlink from any parent collections
    for parent in list(bpy.data.collections):
        try:
            if parent.children.get(coll.name):
                parent.children.unlink(coll)
        except Exception:
            pass

    try:
        bpy.data.collections.remove(coll)
    except Exception:
        pass


# ----------------------------
# SVG schematic import
# ----------------------------

def plane_rotation_for_schematic(plane: str) -> Euler:
    """Return rotation that maps imported SVG (XY plane) to desired plane."""
    p = plane.upper().strip()
    if p == "XZ":
        # Map SVG +Y to world +Z; keep plane at Y=0.
        return Euler((math.radians(90.0), 0.0, 0.0), "XYZ")
    if p == "YZ":
        # First XY -> XZ, then X axis -> Y axis.
        return Euler((math.radians(90.0), 0.0, math.radians(90.0)), "XYZ")
    raise ValueError(f"Unsupported schematic plane: {plane!r} (expected 'XZ' or 'YZ')")


def import_svg_as_curves(svg_path: str) -> List[bpy.types.Object]:
    """Import SVG and return newly-created objects."""
    ensure_addon_enabled("io_curve_svg")

    before = {o.name for o in bpy.data.objects}

    # The import operator usually selects imported objects.
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.import_curve.svg(filepath=svg_path)

    after = {o.name for o in bpy.data.objects}
    new_names = sorted(after - before)
    return [bpy.data.objects[n] for n in new_names if n in bpy.data.objects]


def configure_curve_object(
    obj: bpy.types.Object,
    *,
    extrude_mm: float,
    bevel_depth_mm: float,
    bevel_resolution: int,
    fill_mode: str,
    use_fill_caps: bool,
    mat: Optional[bpy.types.Material],
) -> None:
    if obj.type != "CURVE":
        return

    c = obj.data
    try:
        c.dimensions = "2D"
    except Exception:
        pass

    try:
        c.fill_mode = fill_mode
    except Exception:
        pass

    try:
        c.use_fill_caps = bool(use_fill_caps)
    except Exception:
        pass

    # Curve geometry (subtle 3D)
    try:
        c.extrude = float(extrude_mm)
    except Exception:
        pass

    try:
        c.bevel_depth = float(bevel_depth_mm)
        c.bevel_resolution = int(bevel_resolution)
    except Exception:
        pass

    # Material
    if mat is not None:
        try:
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)
        except Exception:
            pass


def build_schematic(
    *,
    side: str,
    cfg: Dict[str, Any],
    defaults: Dict[str, Any],
    manifest_path: Path,
    stub: str,
    rig_parent: bpy.types.Object,
    rig_coll: bpy.types.Collection,
    src_coll: bpy.types.Collection,
) -> None:
    side_key = side.upper()
    svg_rel = cfg.get("svg")
    if not svg_rel:
        print(f"[build] No schematic.svg configured for {side_key}; skipping")
        return

    svg_path = resolve_path(manifest_path, svg_rel)
    if not Path(svg_path).exists():
        raise FileNotFoundError(f"Schematic SVG not found: {svg_path}")

    plane = str(cfg.get("plane", "XZ")).upper()
    scale = cfg.get("scale", 1.0)

    # Anchor at the origin (nice for editing)
    anchor = ensure_empty(f"RIG_{stub}_{side_key}_SCHEMATIC_ANCHOR", (0.0, 0.0, 0.0))
    anchor.parent = rig_parent
    move_object_to_collection(anchor, rig_coll)

    xform = ensure_empty(f"RIG_{stub}_{side_key}_SCHEMATIC_XFORM", (0.0, 0.0, 0.0))
    xform.parent = anchor
    move_object_to_collection(xform, rig_coll)

    # Orientation + scale
    xform.rotation_euler = plane_rotation_for_schematic(plane)
    xform.scale = Vector(coerce_scale(scale))

    # Material from defaults (overrideable per side)
    mat_cfg = defaults.get("material", {})
    mat_name = str(cfg.get("material", mat_cfg.get("name", "MAT_SchematicInk")))
    color = cfg.get("color_rgba", mat_cfg.get("color_rgba", [0.05, 0.05, 0.05, 1.0]))
    rough = float(cfg.get("roughness", mat_cfg.get("roughness", 0.45)))
    spec = float(cfg.get("specular", mat_cfg.get("specular", 0.15)))
    metal = float(cfg.get("metallic", mat_cfg.get("metallic", 0.0)))
    mat = ensure_material_principled(
        mat_name,
        color_rgba=[float(color[0]), float(color[1]), float(color[2]), float(color[3])],
        roughness=rough,
        specular=spec,
        metallic=metal,
    )

    # Geometry defaults (overrideable)
    geom = defaults.get("geometry", {})
    extrude_mm = float(cfg.get("extrude_mm", geom.get("extrude_mm", 0.02)))
    bevel_depth_mm = float(cfg.get("bevel_depth_mm", geom.get("bevel_depth_mm", 0.10)))
    bevel_resolution = int(cfg.get("bevel_resolution", geom.get("bevel_resolution", 2)))
    fill_mode = str(cfg.get("fill_mode", geom.get("fill_mode", "BOTH")))
    use_fill_caps = bool(cfg.get("use_fill_caps", geom.get("use_fill_caps", True)))

    # Extrude "into" the corner for nicer shadows.
    # - XZ plane: inward is +Y (our rotation makes curve normal -Y), so use negative extrude.
    # - YZ plane: inward is +X (our rotation makes curve normal +X), so use positive extrude.
    if plane == "XZ":
        extrude_mm = -abs(extrude_mm)
    else:
        extrude_mm = abs(extrude_mm)

    # Import
    imported = import_svg_as_curves(svg_path)
    curve_objs = [o for o in imported if o.type == "CURVE"]

    # Parent + move into our SRC collection
    for o in curve_objs:
        o.parent = xform
        try:
            o.matrix_parent_inverse = xform.matrix_world.inverted()
        except Exception:
            pass
        move_object_to_collection(o, src_coll)
        configure_curve_object(
            o,
            extrude_mm=extrude_mm,
            bevel_depth_mm=bevel_depth_mm,
            bevel_resolution=bevel_resolution,
            fill_mode=fill_mode,
            use_fill_caps=use_fill_caps,
            mat=mat,
        )

    # Align corner to origin: shift along the axes that define the corner.
    # We do this AFTER parenting so rotation+scale are included.
    bpy.context.view_layer.update()

    vmin, _vmax = bbox_world(curve_objs)
    if plane == "XZ":
        shift = Vector((-vmin.x, -vmin.y, -vmin.z))
    else:
        shift = Vector((-vmin.x, -vmin.y, -vmin.z))

    xform.location += shift

    print(f"[build] Imported schematic {side_key} ({plane}) from {svg_rel} -> aligned corner to origin")


# ----------------------------
# Component instance import
# ----------------------------

def build_component_instance(
    *,
    name: str,
    cfg: Dict[str, Any],
    manifest_path: Path,
    rig_parent: bpy.types.Object,
    rig_coll: bpy.types.Collection,
    src_coll: bpy.types.Collection,
) -> None:
    blend_rel = cfg.get("blend") or cfg.get("filepath") or cfg.get("path")
    if not blend_rel:
        print(f"[build] No blend path for component {name}; skipping")
        return

    blend_path = resolve_path(manifest_path, blend_rel)
    if not Path(blend_path).exists():
        raise FileNotFoundError(f"Component blend not found: {blend_path}")

    requested_collection = cfg.get("collection") or cfg.get("blend_collection")
    link = bool(cfg.get("link", True))

    coll = load_collection_from_blend(
        blend_path,
        collection_name=str(requested_collection) if requested_collection else None,
        fallback_names=(
            str(requested_collection) if requested_collection else "",
            "Collection",
        ),
        link=link,
    )

    anchor = ensure_empty(f"RIG_{name}", (0.0, 0.0, 0.0))
    anchor.parent = rig_parent
    move_object_to_collection(anchor, rig_coll)

    loc = cfg.get("location_mm", [0.0, 0.0, 0.0])
    rot = cfg.get("rotation_deg", [0.0, 0.0, 0.0])
    sc = coerce_scale(cfg.get("scale", 1.0))
    set_world_transform(anchor, loc, rot, sc)

    inst_name = f"INST_{name}"
    old = bpy.data.objects.get(inst_name)
    if old is not None:
        try:
            bpy.data.objects.remove(old, do_unlink=True)
        except Exception:
            pass

    inst = bpy.data.objects.new(inst_name, None)
    bpy.context.scene.collection.objects.link(inst)
    move_object_to_collection(inst, src_coll)

    inst.empty_display_type = "PLAIN_AXES"
    inst.instance_type = "COLLECTION"
    inst.instance_collection = coll

    inst.parent = anchor
    try:
        inst.matrix_parent_inverse = anchor.matrix_world.inverted()
    except Exception:
        pass

    print(
        f"[build] Component {name}: {Path(blend_rel).as_posix()}::{requested_collection or '(auto)'} "
        f"(link={link})"
    )


# ----------------------------
# Preview camera
# ----------------------------

def build_preview_camera(cfg: Dict[str, Any], rig_stub: str, rig_root: bpy.types.Object) -> None:
    pcfg = cfg.get("preview_camera", {})
    if not pcfg.get("enabled", True):
        return

    cam_name = str(pcfg.get("name", "CAM_ElectroMechIso"))
    cam = ensure_camera(cam_name)

    try:
        cam.data.type = "PERSP"
        cam.data.lens = float(pcfg.get("lens_mm", 85.0))
        cam.data.sensor_fit = "HORIZONTAL"
        cam.data.sensor_width = float(pcfg.get("sensor_width_mm", 36.0))
    except Exception:
        pass

    cam.location = Vector(pcfg.get("location_mm", [600.0, 600.0, 600.0]))
    try:
        cam.data.clip_start = float(pcfg.get("clip_start_mm", 10.0))
        cam.data.clip_end = float(pcfg.get("clip_end_mm", 200000.0))
    except Exception:
        pass

    target = ensure_empty(f"EMPTY_{rig_stub}_CamTarget", pcfg.get("target_mm", [0.0, 0.0, 0.0]))

    ensure_track_to(cam, target, track_axis="TRACK_NEGATIVE_Z", up_axis="UP_Y")

    # Nice for interactive viewing when opening this asset file.
    try:
        bpy.context.scene.camera = cam
    except Exception:
        pass


# ----------------------------
# Main build
# ----------------------------

def load_manifest(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_from_manifest(manifest_path: Path, *, output_override: Optional[str] = None) -> str:
    cfg = load_manifest(manifest_path)

    if bool(cfg.get("scene", {}).get("remove_startup_objects", True)):
        remove_startup_objects()

    apply_units(cfg)
    apply_world_settings(cfg)

    out_cfg = cfg.get("output", {})
    export_name = str(out_cfg.get("export_collection", "EXPORT_electrical_mechanical"))
    out_rel = str(out_cfg.get("blend_path", "assets/compiled/blend/electrical_mechanical.blend"))

    if output_override:
        out_rel = output_override

    out_path = Path(resolve_path(manifest_path, out_rel)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Rebuild export collection cleanly (useful in interactive sessions).
    old_export = bpy.data.collections.get(export_name)
    if old_export is not None:
        delete_collection_recursive(old_export)

    export_coll = ensure_collection(export_name)

    stub = export_name[len("EXPORT_") :] if export_name.startswith("EXPORT_") else export_name
    src_coll = ensure_child_collection(export_coll, f"SRC_{stub}")
    rig_coll = ensure_child_collection(export_coll, f"RIG_{stub}")

    # Root rig empty (handy handle if you open the asset file)
    rig_root = ensure_empty(f"RIG_{stub}_ROOT", (0.0, 0.0, 0.0))
    move_object_to_collection(rig_root, rig_coll)

    # Schematics (walls)
    svg_defaults = cfg.get("svg_defaults", {})
    schem = cfg.get("schematics", {})
    if "left" in schem:
        build_schematic(
            side="left",
            cfg=schem.get("left", {}),
            defaults=svg_defaults,
            manifest_path=manifest_path,
            stub=stub,
            rig_parent=rig_root,
            rig_coll=rig_coll,
            src_coll=src_coll,
        )
    if "right" in schem:
        build_schematic(
            side="right",
            cfg=schem.get("right", {}),
            defaults=svg_defaults,
            manifest_path=manifest_path,
            stub=stub,
            rig_parent=rig_root,
            rig_coll=rig_coll,
            src_coll=src_coll,
        )

    # Components (floor)
    comps = cfg.get("components", {})

    def maybe(cfg_side: Dict[str, Any], key: str) -> Dict[str, Any]:
        v = cfg_side.get(key, {})
        return v if isinstance(v, dict) else {}

    left = comps.get("left", {}) if isinstance(comps.get("left", {}), dict) else {}
    right = comps.get("right", {}) if isinstance(comps.get("right", {}), dict) else {}

    build_component_instance(
        name=f"{stub}_LEFT_ELECTRICAL",
        cfg=maybe(left, "electrical"),
        manifest_path=manifest_path,
        rig_parent=rig_root,
        rig_coll=rig_coll,
        src_coll=src_coll,
    )
    build_component_instance(
        name=f"{stub}_LEFT_MECHANICAL",
        cfg=maybe(left, "mechanical"),
        manifest_path=manifest_path,
        rig_parent=rig_root,
        rig_coll=rig_coll,
        src_coll=src_coll,
    )
    build_component_instance(
        name=f"{stub}_RIGHT_ELECTRICAL",
        cfg=maybe(right, "electrical"),
        manifest_path=manifest_path,
        rig_parent=rig_root,
        rig_coll=rig_coll,
        src_coll=src_coll,
    )
    build_component_instance(
        name=f"{stub}_RIGHT_MECHANICAL",
        cfg=maybe(right, "mechanical"),
        manifest_path=manifest_path,
        rig_parent=rig_root,
        rig_coll=rig_coll,
        src_coll=src_coll,
    )

    build_preview_camera(cfg, stub, rig_root)

    # Save + make library paths relative (important if you move the repo around)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path), check_existing=False, compress=True)

    try:
        bpy.ops.file.make_paths_relative()
        bpy.ops.wm.save_mainfile()
    except Exception:
        pass

    print(f"[build] Wrote: {out_path}")
    print(f"[build] Export collection: {export_name}")

    return str(out_path)


def main() -> None:
    args = parse_args(argv_after_dashes())

    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
    else:
        manifest_path = (Path(__file__).resolve().parent / "manifest.json").resolve()

    build_from_manifest(manifest_path, output_override=args.output)


if __name__ == "__main__":
    main()
