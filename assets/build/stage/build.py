"""
build_trial_stage_frames.py

Blender script to generate a "poster" style stage-motion stack by duplicating
EXPORT_stage many times and dialing yaw/pitch per frame from a JSON manifest.

Usage (recommended):
  blender --background --factory-startup \
    --python build_trial_stage_frames.py -- \
    --manifest /path/to/trial_stage_frames_manifest.json \
    --out /path/to/trial_stage_frames.blend \
    --layout both

Layouts:
  - stacked : all frames at same location (z_span_factor=0)
  - timez   : frames translated along +Z over time (z_span_factor>0)
  - both    : create both in separate collections

Notes:
  - Uses APPEND (not LINK) and uses object copies that share mesh datablocks
    (a "linked duplicate" style) so file size stays reasonable.
  - Applies yaw/pitch as a delta about each rig empty's local Z axis via
    quaternion multiplication, preserving any base alignment rotations.
"""

import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Quaternion, Vector


# ----------------------------
# CLI helpers
# ----------------------------

def _parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True, help="Path to manifest JSON")
    p.add_argument("--out", required=True, help="Output .blend path")
    p.add_argument("--layout", default="both", choices=["stacked", "timez", "both"],
                   help="Which layout(s) to build")
    p.add_argument("--no_cleanup", action="store_true",
                   help="Don't delete default objects (cube, camera, light) before building")
    return p.parse_args(argv)


# ----------------------------
# Blender data helpers
# ----------------------------

def cleanup_default_scene():
    # Remove all objects from the current scene.
    # (Leaves datablocks that are used by something else intact.)
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove all collections except the master scene collection
    master = bpy.context.scene.collection
    for col in list(master.children):
        master.children.unlink(col)

    # Purge orphaned collections/objects (optional; safe-ish)
    # NOTE: Purging all orphans can remove data you want to keep. Keep conservative.
    # bpy.ops.outliner.orphans_purge(do_recursive=True)


def append_export_collection(blend_path: str, collection_name: str) -> bpy.types.Collection:
    blend_path = bpy.path.abspath(blend_path)

    if not os.path.exists(blend_path):
        raise FileNotFoundError(f"Blend file not found: {blend_path}")

    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        if collection_name not in data_from.collections:
            raise ValueError(
                f"Collection '{collection_name}' not found in {blend_path}. "
                f"Available: {list(data_from.collections)[:20]}..."
            )
        data_to.collections = [collection_name]

    col = data_to.collections[0]
    if col is None:
        raise RuntimeError(f"Failed to append collection '{collection_name}' from {blend_path}")

    bpy.context.scene.collection.children.link(col)
    return col


def iter_collection_objects_recursive(col: bpy.types.Collection):
    seen = set()

    def _walk(c):
        for obj in c.objects:
            if obj.name not in seen:
                seen.add(obj.name)
                yield obj
        for child in c.children:
            yield from _walk(child)

    yield from _walk(col)


def duplicate_objects_linked(objs, target_collection: bpy.types.Collection):
    """
    Duplicate objects as "linked duplicates":
      - object datablocks are copied (so transforms can differ)
      - mesh datablocks are shared (so file size stays smaller)
    Parenting is remapped to the duplicated parents.

    Returns: mapping {old_obj: new_obj}
    """
    mapping = {}

    # 1) Copy objects
    for o in objs:
        no = o.copy()
        # Share datablocks (Mesh, Curve, etc.) by default. For Mesh this is the
        # main file-size saver.
        no.data = o.data
        mapping[o] = no

    # 2) Link to target collection
    for no in mapping.values():
        target_collection.objects.link(no)

    # 3) Remap parenting + matrix_parent_inverse
    for old, new in mapping.items():
        if old.parent and old.parent in mapping:
            new.parent = mapping[old.parent]
            new.parent_type = old.parent_type
            new.parent_bone = old.parent_bone
            try:
                new.matrix_parent_inverse = old.matrix_parent_inverse.copy()
            except Exception:
                pass

    # 4) Remap constraint targets (rare for this asset, but cheap to support)
    for old, new in mapping.items():
        for c in new.constraints:
            if hasattr(c, "target") and c.target in mapping:
                c.target = mapping[c.target]

    return mapping


def compute_world_bbox_z_span(objs) -> float:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_v = Vector((float("inf"), float("inf"), float("inf")))
    max_v = Vector((float("-inf"), float("-inf"), float("-inf")))

    any_mesh = False
    for obj in objs:
        if obj.type != "MESH":
            continue
        any_mesh = True
        eval_obj = obj.evaluated_get(depsgraph)
        # bound_box is in local space (8 corners)
        for corner in eval_obj.bound_box:
            co = eval_obj.matrix_world @ Vector(corner)
            min_v.x = min(min_v.x, co.x)
            min_v.y = min(min_v.y, co.y)
            min_v.z = min(min_v.z, co.z)
            max_v.x = max(max_v.x, co.x)
            max_v.y = max(max_v.y, co.y)
            max_v.z = max(max_v.z, co.z)

    if not any_mesh:
        return 0.0
    return max_v.z - min_v.z


# ----------------------------
# Rig rotation helpers
# ----------------------------

def apply_local_z_delta_deg(obj: bpy.types.Object, delta_deg: float, base_prop: str = "__base_q"):
    """
    Apply delta rotation about the object's local +Z axis without clobbering
    any pre-alignment rotation.

    Stores the original quaternion into a custom prop (base_prop) the first
    time it is called on that object, then always applies:
        obj.rotation_quaternion = base_q @ q_delta
    """
    obj.rotation_mode = "QUATERNION"

    if base_prop not in obj:
        obj[base_prop] = list(obj.rotation_quaternion)

    base_q = Quaternion(obj[base_prop])
    q_delta = Quaternion((0.0, 0.0, 1.0), math.radians(delta_deg))
    obj.rotation_quaternion = base_q @ q_delta


# ----------------------------
# Main build
# ----------------------------

def build_layout(
    layout_name: str,
    export_collection: bpy.types.Collection,
    stage_objs: list,
    rig_names: dict,
    frames: list,
    base_location=(0.0, 0.0, 0.0),
    z_span_factor: float = 0.0,
):
    """
    Create one layout collection with per-frame duplicated stages.
    """
    top = bpy.data.collections.new(f"TRIAL_STAGE__{layout_name}")
    bpy.context.scene.collection.children.link(top)

    # Find template rig objects by name inside the appended stage set
    tmpl_root = next((o for o in stage_objs if o.name == rig_names["root_name"]), None)
    tmpl_yaw  = next((o for o in stage_objs if o.name == rig_names["yaw_name"]), None)
    tmpl_pitch= next((o for o in stage_objs if o.name == rig_names["pitch_name"]), None)

    if tmpl_root is None or tmpl_yaw is None or tmpl_pitch is None:
        raise RuntimeError(
            "Could not find one or more rig empties in the appended stage. "
            f"Needed: {rig_names}. Found root={tmpl_root}, yaw={tmpl_yaw}, pitch={tmpl_pitch}"
        )

    # Compute Z span from geometry so the "time as Z" spacing adapts to asset scale
    z_total = 0.0
    if z_span_factor and z_span_factor != 0.0:
        z_span = compute_world_bbox_z_span(stage_objs)
        z_total = z_span * float(z_span_factor)

    n = len(frames)
    for f in frames:
        idx = int(f["frame"])

        frame_col = bpy.data.collections.new(f"{layout_name}__F{idx:03d}__{f.get('phase','')}")
        top.children.link(frame_col)

        mapping = duplicate_objects_linked(stage_objs, frame_col)

        # Rename the 3 main rig empties for clarity
        inst_root  = mapping[tmpl_root]
        inst_yaw   = mapping[tmpl_yaw]
        inst_pitch = mapping[tmpl_pitch]
        inst_root.name  = f"{rig_names['root_name']}__{layout_name}__F{idx:03d}"
        inst_yaw.name   = f"{rig_names['yaw_name']}__{layout_name}__F{idx:03d}"
        inst_pitch.name = f"{rig_names['pitch_name']}__{layout_name}__F{idx:03d}"

        # Place the whole stage
        z_off = 0.0
        if z_total and n > 1:
            z_off = z_total * (idx / (n - 1))

        inst_root.location = Vector(base_location) + Vector((0.0, 0.0, z_off))

        # Stash useful per-frame metadata (handy later for transparency/material logic)
        inst_root["frame"] = idx
        inst_root["t_norm"] = float(f.get("t_norm", idx / max(1, n - 1)))
        inst_root["phase"] = f.get("phase", "")
        inst_root["yaw_deg"] = float(f.get("yaw_deg", 0.0))
        inst_root["pitch_deg"] = float(f.get("pitch_deg", 0.0))

        # Apply yaw/pitch deltas (about each empty's local Z)
        apply_local_z_delta_deg(inst_yaw, float(f.get("yaw_deg", 0.0)) * float(rig_names.get("yaw_sign", 1.0)))
        apply_local_z_delta_deg(inst_pitch, float(f.get("pitch_deg", 0.0)) * float(rig_names.get("pitch_sign", 1.0)))

    return top


def main():
    args = _parse_args()

    with open(args.manifest, "r") as f:
        manifest = json.load(f)

    if not args.no_cleanup:
        cleanup_default_scene()

    source = manifest["source_asset"]
    rig = manifest["stage_rig"]
    layouts = manifest.get("layouts", {})
    frames = manifest["frames"]

    export_col = append_export_collection(source["blend_path"], source["export_collection"])

    # Collect ALL objects under the appended export collection (recursively)
    stage_objs = list(iter_collection_objects_recursive(export_col))

    # Hide the appended template export in renders (kept as a hidden template)
    export_col.hide_viewport = True
    export_col.hide_render = True

    want_stacked = args.layout in ("stacked", "both")
    want_timez   = args.layout in ("timez", "both")

    if want_stacked and layouts.get("stacked", {}).get("enabled", True):
        build_layout(
            "stacked",
            export_col,
            stage_objs,
            {**rig, **{"yaw_sign": rig.get("yaw_sign", 1.0), "pitch_sign": rig.get("pitch_sign", 1.0)}},
            frames,
            base_location=layouts.get("stacked", {}).get("base_location", (0.0, 0.0, 0.0)),
            z_span_factor=float(layouts.get("stacked", {}).get("z_span_factor", 0.0)),
        )

    if want_timez and layouts.get("timez", {}).get("enabled", True):
        build_layout(
            "timez",
            export_col,
            stage_objs,
            {**rig, **{"yaw_sign": rig.get("yaw_sign", 1.0), "pitch_sign": rig.get("pitch_sign", 1.0)}},
            frames,
            base_location=layouts.get("timez", {}).get("base_location", (0.0, 0.0, 0.0)),
            z_span_factor=float(layouts.get("timez", {}).get("z_span_factor", 0.2)),
        )

    out_path = bpy.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
