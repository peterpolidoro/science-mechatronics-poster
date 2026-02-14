"""
dump_image_planes.py

Export diagnostic information about image planes in a generated electrical-mechanical .blend.

Why this exists
---------------
When an image on the XZ plane "faces the wrong way", the root cause is almost always one of:
  1) The plane's polygon normal points toward -Y (face winding)
  2) The material is backface-culled, so you only see the "front"
  3) The UV mapping is mirrored/rotated, so the intended "corner at origin" is not the one you expect

This script dumps enough information to diagnose all three:
  - object transform (matrix_world, location/rotation/scale)
  - mesh vertices (local + world)
  - polygon vertex order + world-space normal
  - UVs per loop and a best-effort "vertex->uv" map
  - image datablocks referenced by materials

Usage
-----
Run it against a .blend file:

  blender -b path/to/generated.blend \
    --python assets/build/electrical_mechanical/dump_image_planes.py -- \
    --out /tmp/planes_dump.json

Optional:
  --collection EXPORT_motion      # only inspect objects under this collection
  --name_filter SCHEM_            # only objects whose name contains substring
  --verbose                       # include more node-tree detail

Then upload /tmp/planes_dump.json here.

"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bpy
from mathutils import Matrix, Vector


def argv_after_dashes() -> List[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Output JSON path")
    p.add_argument("--collection", default=None, help="Restrict to objects under this collection name")
    p.add_argument("--name_filter", default=None, help="Substring filter on object names")
    p.add_argument("--verbose", action="store_true", help="Include extra material node information")
    return p.parse_args(argv_after_dashes())


def mat_has_image(mat: bpy.types.Material) -> bool:
    if not mat or not getattr(mat, "use_nodes", False) or not mat.node_tree:
        return False
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and getattr(n, "image", None) is not None:
            return True
    return False


def obj_uses_image(obj: bpy.types.Object) -> bool:
    if not obj or obj.type != "MESH" or not getattr(obj, "data", None):
        return False
    mats = []
    try:
        mats = list(obj.data.materials)
    except Exception:
        mats = []
    return any(mat_has_image(m) for m in mats if m is not None)


def collection_objects_recursive(col: bpy.types.Collection) -> List[bpy.types.Object]:
    out: List[bpy.types.Object] = []
    def _walk(c: bpy.types.Collection) -> None:
        try:
            out.extend(list(c.objects))
        except Exception:
            pass
        try:
            for ch in c.children:
                _walk(ch)
        except Exception:
            pass
    _walk(col)
    # Deduplicate by name (Blender object names are unique within bpy.data.objects)
    uniq = []
    seen = set()
    for o in out:
        if o and o.name not in seen:
            uniq.append(o)
            seen.add(o.name)
    return uniq


def matrix_to_list(m: Matrix) -> List[List[float]]:
    return [[float(m[r][c]) for c in range(4)] for r in range(4)]


def vector3(v: Vector) -> List[float]:
    return [float(v.x), float(v.y), float(v.z)]


def get_world_normal(obj: bpy.types.Object, local_normal: Vector) -> List[float]:
    try:
        wn = (obj.matrix_world.to_3x3() @ local_normal).normalized()
        return vector3(wn)
    except Exception:
        return [0.0, 0.0, 0.0]


def dump_material(mat: bpy.types.Material, *, verbose: bool) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": mat.name if mat else None,
        "use_nodes": bool(getattr(mat, "use_nodes", False)),
    }
    # backface culling (version dependent)
    for prop in ("use_backface_culling", "backface_culling"):
        if hasattr(mat, prop):
            try:
                d["backface_culling"] = bool(getattr(mat, prop))
                break
            except Exception:
                pass

    # transparency method (version dependent)
    for prop in ("surface_render_method", "blend_method"):
        if hasattr(mat, prop):
            try:
                d[prop] = str(getattr(mat, prop))
            except Exception:
                pass

    imgs = []
    if mat and getattr(mat, "use_nodes", False) and mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and getattr(n, "image", None) is not None:
                img = n.image
                imgs.append({
                    "node": n.name,
                    "image_name": img.name,
                    "image_filepath": img.filepath,
                    "size_px": [int(img.size[0]), int(img.size[1])] if getattr(img, "size", None) else None,
                    "colorspace": getattr(getattr(img, "colorspace_settings", None), "name", None),
                    "alpha_mode": getattr(img, "alpha_mode", None),
                })
    d["images"] = imgs

    if verbose and mat and mat.node_tree:
        d["nodes"] = [{"name": n.name, "type": n.type} for n in mat.node_tree.nodes]

    return d


def dump_mesh_object(obj: bpy.types.Object, *, verbose: bool) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "location": vector3(obj.location),
        "rotation_euler": vector3(obj.rotation_euler),
        "scale": vector3(obj.scale),
        "matrix_world": matrix_to_list(obj.matrix_world),
        "world_bbox": [vector3(obj.matrix_world @ Vector(corner)) for corner in obj.bound_box] if getattr(obj, "bound_box", None) else None,
    }

    me = obj.data
    # vertices local/world
    verts_local = [vector3(v.co) for v in me.vertices]
    verts_world = [vector3(obj.matrix_world @ v.co) for v in me.vertices]
    data["mesh"] = {
        "verts_local": verts_local,
        "verts_world": verts_world,
    }

    # find vertex closest to origin
    origin = Vector((0.0, 0.0, 0.0))
    min_idx = None
    min_d = None
    for i, v in enumerate(me.vertices):
        vw = obj.matrix_world @ v.co
        d = (vw - origin).length
        if min_d is None or d < min_d:
            min_d = d
            min_idx = i
    data["mesh"]["closest_vertex_to_world_origin"] = {
        "index": int(min_idx) if min_idx is not None else None,
        "distance": float(min_d) if min_d is not None else None,
        "coord_world": verts_world[min_idx] if min_idx is not None and min_idx < len(verts_world) else None,
        "coord_local": verts_local[min_idx] if min_idx is not None and min_idx < len(verts_local) else None,
    }

    # polygons
    polys = []
    for p in me.polygons:
        polys.append({
            "index": int(p.index),
            "vertex_indices": [int(i) for i in p.vertices],
            "normal_local": vector3(p.normal),
            "normal_world": get_world_normal(obj, p.normal),
            "normal_world_dot_plusY": float(Vector(get_world_normal(obj, p.normal)).dot(Vector((0.0, 1.0, 0.0)))),
            "normal_world_dot_minusY": float(Vector(get_world_normal(obj, p.normal)).dot(Vector((0.0, -1.0, 0.0)))),
        })
    data["mesh"]["polygons"] = polys

    # UVs (best effort)
    uv_info: Dict[str, Any] = {"active": None, "layers": []}
    if me.uv_layers:
        uv_info["active"] = me.uv_layers.active.name if me.uv_layers.active else None
        for layer in me.uv_layers:
            layer_dump = {"name": layer.name, "uvs_per_loop": []}
            # For each poly, list loop vertex index + uv
            for p in me.polygons:
                loops = []
                for li in p.loop_indices:
                    vidx = int(me.loops[li].vertex_index)
                    uv = layer.data[li].uv
                    loops.append({"loop_index": int(li), "vertex_index": vidx, "uv": [float(uv.x), float(uv.y)]})
                layer_dump["uvs_per_poly"] = layer_dump.get("uvs_per_poly", [])
                layer_dump["uvs_per_poly"].append({"poly_index": int(p.index), "loops": loops})
            uv_info["layers"].append(layer_dump)

            # build a vertex->uv map by averaging uvs for each vertex
            vmap: Dict[int, Tuple[float, float, int]] = {}
            for li, loop in enumerate(me.loops):
                try:
                    uv = layer.data[li].uv
                except Exception:
                    continue
                vidx = int(loop.vertex_index)
                if vidx not in vmap:
                    vmap[vidx] = (float(uv.x), float(uv.y), 1)
                else:
                    sx, sy, n = vmap[vidx]
                    vmap[vidx] = (sx + float(uv.x), sy + float(uv.y), n + 1)
            vmap_out = {}
            for vidx, (sx, sy, n) in vmap.items():
                vmap_out[str(vidx)] = [sx / n, sy / n]
            layer_dump["vertex_uv_map"] = vmap_out

    data["mesh"]["uv"] = uv_info

    # materials
    mats = []
    try:
        mats = list(me.materials)
    except Exception:
        mats = []
    data["materials"] = [dump_material(m, verbose=verbose) for m in mats if m is not None]

    return data


def main() -> None:
    args = parse_args()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    col_filter = args.collection
    name_filter = args.name_filter

    # Gather candidates
    objs: List[bpy.types.Object] = []

    if col_filter:
        col = bpy.data.collections.get(col_filter)
        if not col:
            print(f"[dump_image_planes][WARN] Collection not found: {col_filter!r}. Available collections: {len(bpy.data.collections)}")
        else:
            objs = collection_objects_recursive(col)
    else:
        objs = list(bpy.data.objects)

    # Filter by name substring (optional)
    if name_filter:
        objs = [o for o in objs if o and name_filter in o.name]

    # Focus on mesh objects that use image textures, but still list a small sample of non-image meshes for context
    image_meshes = [o for o in objs if o and o.type == "MESH" and obj_uses_image(o)]

    report: Dict[str, Any] = {
        "blend_file": bpy.data.filepath,
        "num_objects_scanned": len(objs),
        "num_image_mesh_objects": len(image_meshes),
        "image_mesh_objects": [],
        "images_datablocks": [],
    }

    for o in image_meshes:
        report["image_mesh_objects"].append(dump_mesh_object(o, verbose=bool(args.verbose)))

    # Dump images datablocks
    for img in bpy.data.images:
        try:
            report["images_datablocks"].append({
                "name": img.name,
                "filepath": img.filepath,
                "size_px": [int(img.size[0]), int(img.size[1])] if getattr(img, "size", None) else None,
                "colorspace": getattr(getattr(img, "colorspace_settings", None), "name", None),
                "alpha_mode": getattr(img, "alpha_mode", None),
                "packed_file": bool(getattr(img, "packed_file", None) is not None),
                "users": int(getattr(img, "users", 0)),
            })
        except Exception:
            pass

    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[dump_image_planes] wrote: {out_path}")
    print(f"[dump_image_planes] image mesh objects: {len(image_meshes)}")
    if image_meshes:
        print("[dump_image_planes] objects:")
        for o in image_meshes:
            print("  -", o.name)


if __name__ == "__main__":
    main()
