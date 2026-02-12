# Blender debug dump for electrical-mechanical asset builds
#
# Usage examples (run from repo root):
#
# 1) Inspect an already-built asset file:
#    blender -b assets/compiled/blend/motion.blend \
#      --python assets/build/electrical_mechanical/debug_dump.py -- \
#      --manifest assets/build/electrical_mechanical/motion-manifest.json \
#      --out /tmp/motion_debug.json
#
# 2) Inspect whatever .blend is currently open (UI or CLI):
#    blender yourfile.blend --python assets/build/electrical_mechanical/debug_dump.py -- \
#      --out /tmp/debug.json
#
# The script writes a JSON report and prints a short summary to stdout.
#
# Notes:
# - Robust to missing/disabled assets in the manifest.
# - Intended to help diagnose whether collections were imported/linked,
#   and whether instances landed at the expected transforms.

import argparse
import json
import math
import os
import sys
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple

import bpy
from mathutils import Vector


# ----------------------------
# Helpers: paths + JSON safety
# ----------------------------

def _abspath(p: str, base_dir: Optional[str] = None) -> str:
    if not p:
        return p
    if os.path.isabs(p):
        return os.path.normpath(p)
    base = base_dir or os.getcwd()
    return os.path.normpath(os.path.abspath(os.path.join(base, p)))


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _vec_to_list(v: Any) -> List[float]:
    try:
        return [float(v[0]), float(v[1]), float(v[2])]
    except Exception:
        return []


def _matrix_to_list(m) -> List[List[float]]:
    try:
        return [[float(m[r][c]) for c in range(4)] for r in range(4)]
    except Exception:
        return []


def _euler_deg(eul) -> List[float]:
    try:
        return [math.degrees(float(eul.x)), math.degrees(float(eul.y)), math.degrees(float(eul.z))]
    except Exception:
        return []


def _quat_list(q) -> List[float]:
    try:
        return [float(q.w), float(q.x), float(q.y), float(q.z)]
    except Exception:
        return []


def _to_mm(v: List[float], mm_per_bu: float) -> List[float]:
    return [float(v[0]) * mm_per_bu, float(v[1]) * mm_per_bu, float(v[2]) * mm_per_bu]


def _bbox_world(obj) -> Optional[Dict[str, Any]]:
    """Compute world-space bounding box for objects that expose bound_box."""
    try:
        bb = obj.bound_box  # 8 corners in local space
        if not bb:
            return None
        corners_world = [obj.matrix_world @ Vector(c) for c in bb]
        xs = [c.x for c in corners_world]
        ys = [c.y for c in corners_world]
        zs = [c.z for c in corners_world]
        vmin = Vector((min(xs), min(ys), min(zs)))
        vmax = Vector((max(xs), max(ys), max(zs)))
        dims = vmax - vmin
        return {
            "min": [float(vmin.x), float(vmin.y), float(vmin.z)],
            "max": [float(vmax.x), float(vmax.y), float(vmax.z)],
            "dims": [float(dims.x), float(dims.y), float(dims.z)],
        }
    except Exception:
        return None


# ----------------------------
# Collection graph utilities
# ----------------------------

def _collection_children(coll) -> List["bpy.types.Collection"]:
    try:
        return list(coll.children)
    except Exception:
        return []


def _collection_objects(coll) -> List["bpy.types.Object"]:
    try:
        return list(coll.objects)
    except Exception:
        return []


def _collection_tree(root_coll, max_objects_per_collection: int = 50, visited: Optional[Set[str]] = None) -> Dict[str, Any]:
    if visited is None:
        visited = set()
    name = getattr(root_coll, "name", "<unknown>")
    node_id = name
    if node_id in visited:
        return {"name": name, "cycle": True}
    visited.add(node_id)

    objects = _collection_objects(root_coll)
    obj_names = [o.name for o in objects]
    if max_objects_per_collection is not None and len(obj_names) > max_objects_per_collection:
        obj_names = obj_names[:max_objects_per_collection] + [f"... ({len(objects) - max_objects_per_collection} more)"]

    lib_path = None
    try:
        if root_coll.library:
            lib_path = root_coll.library.filepath
    except Exception:
        lib_path = None

    out = {
        "name": name,
        "hide_viewport": bool(getattr(root_coll, "hide_viewport", False)),
        "hide_render": bool(getattr(root_coll, "hide_render", False)),
        "library_filepath": lib_path,
        "objects": obj_names,
        "children": [],
    }
    for ch in _collection_children(root_coll):
        out["children"].append(_collection_tree(ch, max_objects_per_collection=max_objects_per_collection, visited=visited))
    return out


def _collections_reachable_from_scene(scene) -> Set[str]:
    reachable: Set[str] = set()
    stack = [scene.collection]
    while stack:
        c = stack.pop()
        if c is None:
            continue
        if c.name in reachable:
            continue
        reachable.add(c.name)
        try:
            stack.extend(list(c.children))
        except Exception:
            pass
    return reachable


def _is_collection_in_scene(scene, coll_name: str) -> bool:
    if not scene or not coll_name:
        return False
    reachable = _collections_reachable_from_scene(scene)
    return coll_name in reachable


def _objects_in_collection_recursive(coll) -> List["bpy.types.Object"]:
    objs: Set["bpy.types.Object"] = set()

    def _rec(c):
        try:
            for o in c.objects:
                objs.add(o)
        except Exception:
            pass
        try:
            for ch in c.children:
                _rec(ch)
        except Exception:
            pass

    _rec(coll)
    return list(objs)


def _union_bbox_for_objects(objs: List["bpy.types.Object"]) -> Optional[Dict[str, Any]]:
    mins = []
    maxs = []
    for o in objs:
        bb = _bbox_world(o)
        if not bb:
            continue
        mins.append(Vector(bb["min"]))
        maxs.append(Vector(bb["max"]))
    if not mins:
        return None
    vmin = Vector((min(v.x for v in mins), min(v.y for v in mins), min(v.z for v in mins)))
    vmax = Vector((max(v.x for v in maxs), max(v.y for v in maxs), max(v.z for v in maxs)))
    dims = vmax - vmin
    return {"min": [float(vmin.x), float(vmin.y), float(vmin.z)],
            "max": [float(vmax.x), float(vmax.y), float(vmax.z)],
            "dims": [float(dims.x), float(dims.y), float(dims.z)]}


# ----------------------------
# Object serialization
# ----------------------------

def _object_to_dict(obj, scene, mm_per_bu: float) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    d["name"] = obj.name
    d["type"] = obj.type
    d["data_name"] = getattr(obj.data, "name", None)

    # visibility
    d["hide_viewport"] = bool(getattr(obj, "hide_viewport", False))
    d["hide_render"] = bool(getattr(obj, "hide_render", False))
    try:
        d["hide_get"] = bool(obj.hide_get())
    except Exception:
        d["hide_get"] = None
    try:
        d["visible_get"] = bool(obj.visible_get())
    except Exception:
        d["visible_get"] = None

    # library linkage
    lib = None
    try:
        if obj.library:
            lib = obj.library.filepath
    except Exception:
        lib = None
    d["library_filepath"] = lib

    # transforms
    try:
        d["location_bu"] = _vec_to_list(obj.location)
        d["location_mm"] = _to_mm(d["location_bu"], mm_per_bu)
    except Exception:
        d["location_bu"] = []
        d["location_mm"] = []

    try:
        d["rotation_mode"] = obj.rotation_mode
        d["rotation_euler_deg"] = _euler_deg(obj.rotation_euler)
        d["rotation_quaternion"] = _quat_list(obj.rotation_quaternion)
    except Exception:
        d["rotation_mode"] = None
        d["rotation_euler_deg"] = []
        d["rotation_quaternion"] = []

    try:
        d["scale"] = _vec_to_list(obj.scale)
    except Exception:
        d["scale"] = []

    try:
        d["matrix_world"] = _matrix_to_list(obj.matrix_world)
    except Exception:
        d["matrix_world"] = []

    # parenting
    d["parent"] = obj.parent.name if obj.parent else None

    # collections membership
    try:
        d["users_collection"] = [c.name for c in obj.users_collection]
    except Exception:
        d["users_collection"] = []

    # instance collections (empties)
    try:
        d["instance_type"] = obj.instance_type
    except Exception:
        d["instance_type"] = None

    try:
        ic = obj.instance_collection
        d["instance_collection"] = ic.name if ic else None
    except Exception:
        d["instance_collection"] = None

    # bounding box + dimensions
    bb = _bbox_world(obj)
    if bb:
        d["bound_box_world_bu"] = bb
        d["bound_box_world_mm"] = {
            "min": _to_mm(bb["min"], mm_per_bu),
            "max": _to_mm(bb["max"], mm_per_bu),
            "dims": _to_mm(bb["dims"], mm_per_bu),
        }
    else:
        d["bound_box_world_bu"] = None
        d["bound_box_world_mm"] = None

    try:
        dims = obj.dimensions
        d["dimensions_bu"] = _vec_to_list(dims)
        d["dimensions_mm"] = _to_mm(d["dimensions_bu"], mm_per_bu)
    except Exception:
        d["dimensions_bu"] = []
        d["dimensions_mm"] = []

    # mesh stats (optional but useful)
    if obj.type == "MESH" and getattr(obj, "data", None) is not None:
        try:
            d["mesh_vertex_count"] = len(obj.data.vertices)
            d["mesh_face_count"] = len(obj.data.polygons)
        except Exception:
            d["mesh_vertex_count"] = None
            d["mesh_face_count"] = None

    # materials (names only)
    try:
        mats = []
        if obj.type == "MESH" and obj.data and hasattr(obj.data, "materials"):
            mats = [m.name for m in obj.data.materials if m]
        d["materials"] = mats
    except Exception:
        d["materials"] = []

    return d


# ----------------------------
# Manifest parsing + checks
# ----------------------------

def _load_manifest(manifest_path: str) -> Optional[Dict[str, Any]]:
    if not manifest_path:
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _get_with_defaults(obj: Dict[str, Any], key: str, default: Any) -> Any:
    if obj is None:
        return default
    if key in obj:
        return obj[key]
    return default


def _collect_expected_from_manifest(m: Dict[str, Any]) -> Dict[str, Any]:
    expected: Dict[str, Any] = {"export_collection": None, "output_blend": None, "schematics": {}, "components": {}}
    if not m:
        return expected
    output = m.get("output", {}) or {}
    expected["export_collection"] = output.get("export_collection")
    expected["output_blend"] = output.get("blend_path")

    # schematics
    schem = m.get("schematics", {}) or {}
    defaults = schem.get("defaults", {}) or {}
    for side in ("left", "right"):
        s = schem.get(side, {}) or {}
        enabled = bool(_get_with_defaults(s, "enabled", defaults.get("enabled", True)))
        expected["schematics"][side] = {
            "enabled": enabled,
            "image_path": s.get("image_path"),
            "plane": s.get("plane"),
            "collection": _get_with_defaults(s, "collection", defaults.get("collection", "SCHEMATICS")),
        }

    # components
    comps = m.get("components", {}) or {}
    comp_defaults = comps.get("defaults", {}) or {}
    for side in ("left", "right"):
        expected["components"][side] = {}
        side_block = comps.get(side, {}) or {}
        for kind in ("electrical", "mechanical"):
            c = side_block.get(kind, {}) or {}
            enabled = bool(_get_with_defaults(c, "enabled", comp_defaults.get("enabled", True)))
            expected["components"][side][kind] = {
                "enabled": enabled,
                "blend": c.get("blend"),
                "blend_collection": c.get("blend_collection"),
                "collection": _get_with_defaults(c, "collection", comp_defaults.get("collection", "COMPONENTS")),
                "link": bool(_get_with_defaults(c, "link", comp_defaults.get("link", True))),
                "location_mm": c.get("location_mm"),
                "rotation_deg": _get_with_defaults(c, "rotation_deg", comp_defaults.get("rotation_deg")),
                "scale": c.get("scale"),
            }
    return expected


def _find_collections_by_base_name(name: str) -> List["bpy.types.Collection"]:
    """Return collections whose name matches name exactly, or name with Blender numeric suffix (.001)."""
    if not name:
        return []
    exact = bpy.data.collections.get(name)
    out = []
    if exact:
        out.append(exact)
    # also find suffixed variants
    prefix = name + "."
    for c in bpy.data.collections:
        if c.name.startswith(prefix):
            out.append(c)
    return out


def _find_instance_objects_for_collection(scene, coll) -> List["bpy.types.Object"]:
    found = []
    for o in scene.objects:
        try:
            if o.instance_type == "COLLECTION" and o.instance_collection == coll:
                found.append(o)
        except Exception:
            continue
    return found


def _normalize_blender_filepath(fp: Optional[str]) -> Optional[str]:
    if not fp:
        return None
    try:
        fp = bpy.path.abspath(fp)
    except Exception:
        pass
    return os.path.normpath(fp)


def _manifest_presence_checks(scene, expected: Dict[str, Any], base_dir: str, mm_per_bu: float) -> Dict[str, Any]:
    checks: Dict[str, Any] = {"export_collection": {}, "schematics": {}, "components": {}}

    # export collection
    exp = expected.get("export_collection")
    checks["export_collection"]["name"] = exp
    if exp:
        checks["export_collection"]["exists_in_bpy_data"] = bool(bpy.data.collections.get(exp))
        checks["export_collection"]["reachable_from_scene"] = _is_collection_in_scene(scene, exp)
    else:
        checks["export_collection"]["exists_in_bpy_data"] = False
        checks["export_collection"]["reachable_from_scene"] = False

    # schematics
    for side, s in expected.get("schematics", {}).items():
        img_path = s.get("image_path")
        enabled = bool(s.get("enabled", True))
        status = {"enabled": enabled, "image_path": img_path}
        abs_img = _abspath(img_path, base_dir) if img_path else None
        status["image_abspath"] = abs_img
        status["image_file_exists_on_disk"] = bool(abs_img and os.path.exists(abs_img))

        # is the image loaded in bpy.data.images?
        if abs_img:
            norm = os.path.normpath(abs_img)
            matches = []
            for im in bpy.data.images:
                fp = _normalize_blender_filepath(getattr(im, "filepath", None))
                if fp and os.path.normpath(fp) == norm:
                    matches.append(im.name)
            status["image_datablocks"] = matches

        checks["schematics"][side] = status

    # components
    for side, kinds in expected.get("components", {}).items():
        checks["components"][side] = {}
        for kind, cfg in kinds.items():
            enabled = bool(cfg.get("enabled", True))
            blend = cfg.get("blend")
            blend_coll = cfg.get("blend_collection")
            status = {
                "enabled": enabled,
                "blend": blend,
                "blend_collection": blend_coll,
                "blend_abspath": _abspath(blend, base_dir) if blend else None,
            }
            status["blend_file_exists_on_disk"] = bool(status["blend_abspath"] and os.path.exists(status["blend_abspath"]))

            # libraries loaded?
            libs = []
            if status["blend_abspath"]:
                norm_blend = os.path.normpath(status["blend_abspath"])
                for lib in bpy.data.libraries:
                    try:
                        fp = _normalize_blender_filepath(lib.filepath)
                    except Exception:
                        fp = lib.filepath
                    if fp and os.path.normpath(fp) == norm_blend:
                        libs.append(fp)
                status["loaded_libraries_matching_blend"] = libs

            # collection present?
            coll_matches = _find_collections_by_base_name(blend_coll) if blend_coll else []
            status["collection_matches_in_bpy_data"] = []
            for c in coll_matches:
                try:
                    status["collection_matches_in_bpy_data"].append({
                        "name": c.name,
                        "library_filepath": c.library.filepath if c.library else None,
                        "reachable_from_scene": _is_collection_in_scene(scene, c.name),
                        "recursive_object_count": len(_objects_in_collection_recursive(c)),
                        "union_bbox_world_mm": None,
                    })
                except Exception:
                    status["collection_matches_in_bpy_data"].append({"name": c.name})

            # instance objects (empties) in the scene for each match
            inst = []
            for c in coll_matches:
                for o in _find_instance_objects_for_collection(scene, c):
                    inst.append({
                        "object": o.name,
                        "location_mm": _to_mm(_vec_to_list(o.location), mm_per_bu),
                        "rotation_euler_deg": _euler_deg(o.rotation_euler),
                        "scale": _vec_to_list(o.scale),
                    })
            status["instance_objects_in_scene"] = inst

            checks["components"][side][kind] = status

    return checks


# ----------------------------
# Main
# ----------------------------

def _parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    p = argparse.ArgumentParser(description="Dump Blender scene + manifest import diagnostics to JSON.")
    p.add_argument("manifest_positional", nargs="?", default=None, help="Optional path to the build manifest JSON.")
    p.add_argument("--manifest", default=None, help="Path to the build manifest JSON.")
    p.add_argument("--out", default=None, help="Output JSON path. Default: <blend>.debug.json next to the opened .blend.")
    p.add_argument("--collection", default=None, help="Export collection name to focus on (overrides manifest).")
    p.add_argument("--max-objects-per-collection", type=int, default=50,
                   help="Limit object name lists inside collection tree nodes (keeps tree readable).")
    p.add_argument("--max-scene-objects", type=int, default=20000,
                   help="Hard cap on scene object serialization (safety).")
    return p.parse_args(argv)


def main() -> int:
    args = _parse_args()

    manifest_path = args.manifest or args.manifest_positional
    base_dir = os.getcwd()

    manifest = _load_manifest(manifest_path) if manifest_path else None
    expected = _collect_expected_from_manifest(manifest) if manifest else {}

    scene = bpy.context.scene
    if scene is None:
        print("[debug_dump] ERROR: No active scene.")
        return 2

    # units conversion
    scale_length = getattr(scene.unit_settings, "scale_length", 1.0) or 1.0
    mm_per_bu = float(scale_length) * 1000.0  # BU -> mm

    export_collection_name = args.collection or (expected.get("export_collection") if expected else None)

    # output path default
    opened_blend = bpy.data.filepath or ""
    if args.out:
        out_path = _abspath(args.out, base_dir)
    else:
        if opened_blend:
            out_path = opened_blend + ".debug.json"
        elif manifest and expected.get("output_blend"):
            out_path = _abspath(expected["output_blend"], base_dir) + ".debug.json"
        else:
            out_path = _abspath("debug_dump.json", base_dir)

    # build report
    report: Dict[str, Any] = {
        "meta": {
            "blender_version": bpy.app.version_string,
            "opened_blend": opened_blend,
            "cwd": base_dir,
            "manifest_path": _abspath(manifest_path, base_dir) if manifest_path else None,
            "export_collection_target": export_collection_name,
        },
        "scene": {
            "name": scene.name,
            "unit_settings": {
                "system": getattr(scene.unit_settings, "system", None),
                "length_unit": getattr(scene.unit_settings, "length_unit", None),
                "scale_length": float(scale_length),
                "mm_per_bu": float(mm_per_bu),
            },
        },
        "libraries": [],
        "images": [],
        "collection_tree": None,
        "orphans": {"collections_not_in_scene_tree": [], "objects_not_in_scene": []},
        "focus": {},
        "manifest_expected": expected if expected else None,
        "manifest_checks": None,
        "warnings": [],
    }

    # libraries
    for lib in bpy.data.libraries:
        try:
            report["libraries"].append({
                "filepath": _normalize_blender_filepath(lib.filepath),
                "name": getattr(lib, "name", None),
            })
        except Exception:
            report["libraries"].append({"filepath": getattr(lib, "filepath", None)})

    # images
    for im in bpy.data.images:
        try:
            report["images"].append({
                "name": im.name,
                "filepath": _normalize_blender_filepath(getattr(im, "filepath", None)),
                "packed": bool(getattr(im, "packed_file", None) is not None),
                "size_px": [int(getattr(im, "size", [0, 0])[0]), int(getattr(im, "size", [0, 0])[1])],
                "users": int(getattr(im, "users", 0)),
            })
        except Exception:
            report["images"].append({"name": im.name})

    # collection tree
    try:
        report["collection_tree"] = _collection_tree(scene.collection, max_objects_per_collection=args.max_objects_per_collection)
    except Exception:
        report["collection_tree"] = {"error": "failed_to_build_collection_tree"}

    # orphan collections
    reachable = _collections_reachable_from_scene(scene)
    for c in bpy.data.collections:
        if c.name not in reachable:
            report["orphans"]["collections_not_in_scene_tree"].append({
                "name": c.name,
                "library_filepath": c.library.filepath if c.library else None,
                "children": [ch.name for ch in getattr(c, "children", [])],
                "objects_count": len(getattr(c, "objects", [])),
            })

    # orphan objects
    scene_obj_names = set(o.name for o in scene.objects)
    for o in bpy.data.objects:
        if o.name not in scene_obj_names:
            report["orphans"]["objects_not_in_scene"].append({
                "name": o.name,
                "type": o.type,
                "library_filepath": o.library.filepath if o.library else None,
                "users_collection": [c.name for c in getattr(o, "users_collection", [])],
            })

    # focus: export collection + its objects (if present and reachable)
    focus: Dict[str, Any] = {}
    if export_collection_name:
        coll = bpy.data.collections.get(export_collection_name)
        focus["export_collection_exists"] = bool(coll)
        focus["export_collection_reachable_from_scene"] = _is_collection_in_scene(scene, export_collection_name)
        if coll:
            objs = _objects_in_collection_recursive(coll)
            focus["export_collection_recursive_object_count"] = len(objs)
            focus["export_collection_union_bbox_world_bu"] = _union_bbox_for_objects(objs)
            if focus["export_collection_union_bbox_world_bu"]:
                bb = focus["export_collection_union_bbox_world_bu"]
                focus["export_collection_union_bbox_world_mm"] = {
                    "min": _to_mm(bb["min"], mm_per_bu),
                    "max": _to_mm(bb["max"], mm_per_bu),
                    "dims": _to_mm(bb["dims"], mm_per_bu),
                }
            else:
                focus["export_collection_union_bbox_world_mm"] = None

            # Serialize objects (bounded to max_scene_objects)
            objs_sorted = sorted(objs, key=lambda o: o.name)
            if len(objs_sorted) > args.max_scene_objects:
                report["warnings"].append(
                    f"Focus export collection has {len(objs_sorted)} objects; truncating to {args.max_scene_objects} in report."
                )
                objs_sorted = objs_sorted[: args.max_scene_objects]
            focus["objects"] = [_object_to_dict(o, scene, mm_per_bu) for o in objs_sorted]
        else:
            focus["objects"] = []
    else:
        focus["note"] = "No export collection specified (use --collection or provide a manifest with output.export_collection)."

    report["focus"] = focus

    # manifest checks (presence, files, matching collections, instances, etc.)
    if manifest and expected:
        report["manifest_checks"] = _manifest_presence_checks(scene, expected, base_dir, mm_per_bu)

        # quick sanity: if components enabled false, mention
        try:
            any_enabled = False
            for side in ("left", "right"):
                for kind in ("electrical", "mechanical"):
                    if expected["components"][side][kind]["enabled"]:
                        any_enabled = True
            if not any_enabled:
                report["warnings"].append(
                    "All components in the manifest have enabled=false, so no electrical/mechanical assets will be imported."
                )
        except Exception:
            pass

    # write output
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    except Exception:
        pass

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # stdout summary
    print("\n[debug_dump] Wrote:", out_path)
    if manifest_path:
        print("[debug_dump] Manifest:", _abspath(manifest_path, base_dir))
    print("[debug_dump] Opened blend:", opened_blend if opened_blend else "<unsaved>")
    print("[debug_dump] Export collection target:", export_collection_name if export_collection_name else "<none>")

    if manifest and expected:
        # Print a concise expected/actual summary
        exp = expected.get("export_collection")
        if exp:
            exists = bool(bpy.data.collections.get(exp))
            reach = _is_collection_in_scene(scene, exp)
            print(f"[debug_dump] export_collection '{exp}': exists={exists}, reachable_from_scene={reach}")

        for side in ("left", "right"):
            s = expected["schematics"].get(side, {})
            if s.get("enabled", True):
                print(f"[debug_dump] schematic.{side}: enabled=True image='{s.get('image_path')}' plane={s.get('plane')}")
            else:
                print(f"[debug_dump] schematic.{side}: enabled=False (skipped)")

        for side in ("left", "right"):
            for kind in ("electrical", "mechanical"):
                c = expected["components"][side][kind]
                print(f"[debug_dump] component.{side}.{kind}: enabled={c.get('enabled')} blend='{c.get('blend')}' collection='{c.get('blend_collection')}'")

        # highlight the likely immediate reason components are missing:
        try:
            all_disabled = all(
                not expected["components"][side][kind]["enabled"]
                for side in ("left", "right")
                for kind in ("electrical", "mechanical")
            )
            if all_disabled:
                print("[debug_dump] NOTE: All 4 components are disabled in the manifest (enabled=false).")
        except Exception:
            pass

    if report.get("warnings"):
        for w in report["warnings"]:
            print("[debug_dump] WARNING:", w)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        print("[debug_dump] FATAL ERROR:\n", traceback.format_exc())
        raise SystemExit(1)
