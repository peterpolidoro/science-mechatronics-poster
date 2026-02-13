"""assets/build/electrical_mechanical/build.py

Electrical–Mechanical "corner" asset builder for the poster (PNG schematics + optional linked collections).

This version focuses on:
- PNG planes (no SVG import issues).
- Robust handling of *missing* manifest assets (images and blend assets can be added gradually).
- Correct transform order so **rotation does not change placement**:
    rotate/scale about an anchor point inside the imported collection,
    then translate the result to location_mm.

Key fix vs earlier versions
---------------------------
The previous pivot/anchor logic attempted to read `obj.matrix_world` from objects
inside a *library-loaded collection* that was **not linked into the scene**.
In that case, Blender often has not evaluated world matrices yet, so the computed
anchor offset becomes (0,0,0). The visible result is that rotating the instance
makes the asset "orbit", and it may appear in the wrong quadrant.

This script computes anchor/bbox offsets by temporarily linking the imported
collection into a hidden evaluation collection in the scene, updating the depsgraph,
and reading evaluated matrices. Then it unlinks the collection again (leaving no
extra planes/cameras/geometry in the final saved file).

It also:
- Does NOT create a camera.
- Deletes any scene cameras defensively.
- Creates the two wall schematic image planes (XZ and YZ), and optionally a center image plane (schematics.center).

Run (from repo root):
  blender -b --factory-startup --python assets/build/electrical_mechanical/build.py -- \
    assets/build/electrical_mechanical/manifest.json

"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import bpy
from mathutils import Euler, Matrix, Vector


# ----------------------------
# CLI helpers
# ----------------------------

def argv_after_dashes() -> List[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build an electrical-mechanical corner .blend from manifest (PNG + collections)")
    p.add_argument("manifest", help="Path to the electrical-mechanical manifest JSON")
    p.add_argument("--output", default=None, help="Override output blend path (defaults to manifest.output.blend_path)")
    p.add_argument("--no-pack-images", action="store_true", help="Disable packing images even if manifest.output.pack_images=true")
    p.add_argument("--no-reset", action="store_true", help="Do not reset Blender to empty file first (advanced)")
    p.add_argument("--debug", action="store_true", help="Print extra debug information")
    return p.parse_args(argv_after_dashes())


# ----------------------------
# Logging
# ----------------------------

def info(msg: str) -> None:
    print(f"[electro_mech] {msg}")


def warn(msg: str) -> None:
    print(f"[electro_mech][WARN] {msg}")


# ----------------------------
# Manifest + path helpers
# ----------------------------

def load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _repo_root_from_manifest(manifest_path: Path) -> Path:
    """Best-effort repo root detection.

    Expected:
      <repo>/assets/build/electrical_mechanical/<manifest>.json
    """
    mp = manifest_path.resolve()
    try:
        cand = mp.parent.parent.parent.parent
        if (cand / "assets").exists():
            return cand
    except Exception:
        pass
    for parent in mp.parents:
        if (parent / "assets").exists():
            return parent
    return mp.parent


def abspath_from_manifest(manifest_path: str | Path, maybe_rel: str | Path) -> str:
    """Resolve a manifest-referenced path.

    - Absolute paths are returned as-is.
    - Relative paths are tried against:
        1) manifest directory
        2) manifest parent
        3) manifest grandparent
        4) repo root
    Returns best candidate even if it doesn't exist (useful for output paths).
    """
    mp = Path(manifest_path).resolve()
    p = Path(maybe_rel)
    if p.is_absolute():
        return str(p)

    bases: List[Path] = [mp.parent, mp.parent.parent, mp.parent.parent.parent]
    repo_root = _repo_root_from_manifest(mp)
    if repo_root not in bases:
        bases.append(repo_root)

    for base in bases:
        cand = (base / p).resolve()
        if cand.exists():
            return str(cand)

    # Prefer repo-root-relative for non-existing paths
    try:
        return str((repo_root / p).resolve())
    except Exception:
        return str((mp.parent / p).resolve())


def merged_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base) if isinstance(base, dict) else {}
    if isinstance(override, dict):
        out.update(override)
    return out


def parse_rotation_deg(spec: Dict[str, Any], default: Sequence[float] = (0.0, 0.0, 0.0)) -> List[float]:
    """Parse rotation settings.

    Supported:
      - rotation_deg: [x, y, z]
      - rotation_deg: <number>  (treated as Z)
      - rot_z_deg / rotation_z_deg / z_rot_deg: overrides Z

    Returns [x, y, z] (degrees).
    """
    rot = spec.get("rotation_deg", None)

    if isinstance(rot, (int, float)):
        out = [0.0, 0.0, float(rot)]
    elif isinstance(rot, (list, tuple)):
        out = [float(default[0]), float(default[1]), float(default[2])]
        if len(rot) > 0:
            try: out[0] = float(rot[0])
            except Exception: pass
        if len(rot) > 1:
            try: out[1] = float(rot[1])
            except Exception: pass
        if len(rot) > 2:
            try: out[2] = float(rot[2])
            except Exception: pass
    else:
        out = [float(default[0]), float(default[1]), float(default[2])]

    for k in ("rot_z_deg", "rotation_z_deg", "z_rot_deg"):
        if k in spec and spec.get(k) is not None:
            try:
                out[2] = float(spec.get(k))
            except Exception:
                pass
            break

    return out


# ----------------------------
# Scene utilities
# ----------------------------

def reset_to_empty_file() -> None:
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    except Exception as e:
        warn(f"read_factory_settings failed: {e!r}")


def apply_units(cfg: Dict[str, Any]) -> None:
    u = cfg.get("units", {}) if isinstance(cfg, dict) else {}
    scene = bpy.context.scene
    try:
        scene.unit_settings.system = u.get("system", "METRIC")
    except Exception:
        pass
    try:
        scene.unit_settings.length_unit = u.get("length_unit", "MILLIMETERS")
    except Exception:
        pass
    try:
        scene.unit_settings.scale_length = float(u.get("scale_length", 0.001))  # 1 BU = 1 mm
    except Exception:
        pass


def ensure_collection(name: str, parent: Optional[bpy.types.Collection] = None) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if parent is None:
        parent = bpy.context.scene.collection
    if parent.children.get(col.name) is None:
        try:
            parent.children.link(col)
        except Exception:
            pass
    return col


def move_object_to_collection(obj: bpy.types.Object, col: bpy.types.Collection) -> None:
    for c in list(obj.users_collection):
        try:
            c.objects.unlink(obj)
        except Exception:
            pass
    if col.objects.get(obj.name) is None:
        try:
            col.objects.link(obj)
        except Exception:
            pass


def ensure_empty_obj(name: str, *, target_collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, None)
        try:
            target_collection.objects.link(obj)
        except Exception:
            bpy.context.scene.collection.objects.link(obj)
    move_object_to_collection(obj, target_collection)
    obj.empty_display_type = "PLAIN_AXES"
    return obj


def parent_keep_local(child: bpy.types.Object, parent: Optional[bpy.types.Object]) -> None:
    child.parent = parent
    try:
        child.matrix_parent_inverse = Matrix.Identity(4)
    except Exception:
        pass


def delete_scene_objects_of_type(obj_type: str) -> None:
    """Delete only objects linked into the current scene."""
    try:
        scene_objs = list(bpy.context.scene.objects)
    except Exception:
        scene_objs = []
    for obj in scene_objs:
        if getattr(obj, "type", None) != obj_type:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


# ----------------------------
# Materials (PNG schematics)
# ----------------------------

def _set_material_transparency(mat: bpy.types.Material, *, method: str = "BLENDED") -> None:
    m = str(method).upper()
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = m
        except Exception:
            pass
    elif hasattr(mat, "blend_method"):
        legacy = {"OPAQUE": "OPAQUE", "BLENDED": "BLEND", "CLIP": "CLIP"}.get(m, "BLEND")
        try:
            mat.blend_method = legacy
        except Exception:
            pass
    if hasattr(mat, "alpha_threshold"):
        try:
            mat.alpha_threshold = 0.5
        except Exception:
            pass


def ensure_material_image_emission(
    name: str,
    image_path: str,
    *,
    emission_strength: float = 1.0,
    interpolation: str = "Cubic",
) -> bpy.types.Material:
    """Unlit image material (Emission) with alpha support."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True

    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (520, 0)

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-840, 0)

    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-560, 0)

    img = bpy.data.images.load(image_path, check_existing=True)
    tex.image = img

    try:
        tex.interpolation = str(interpolation)
    except Exception:
        pass

    try:
        img.alpha_mode = "STRAIGHT"
    except Exception:
        pass

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (-220, 60)
    try:
        emission.inputs["Strength"].default_value = float(emission_strength)
    except Exception:
        pass

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (-220, -140)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (140, 0)

    if "UV" in texcoord.outputs and "Vector" in tex.inputs:
        links.new(texcoord.outputs["UV"], tex.inputs["Vector"])

    links.new(tex.outputs["Color"], emission.inputs["Color"])
    if "Alpha" in tex.outputs:
        links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    _set_material_transparency(mat, method="BLENDED")
    return mat


# ----------------------------
# Corner image planes
# ----------------------------

def _ensure_uv_layer(mesh: bpy.types.Mesh, uvs: Sequence[Tuple[float, float]]) -> None:
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return
    for poly in mesh.polygons:
        if len(poly.loop_indices) != 4:
            continue
        for li, uv in zip(poly.loop_indices, uvs):
            uv_layer.data[li].uv = uv


def _make_corner_plane_mesh(
    mesh_name: str,
    *,
    plane: str,
    width_mm: float,
    height_mm: float,
    flip_u: bool,
    flip_v: bool,
) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.get(mesh_name)
    if mesh is None:
        mesh = bpy.data.meshes.new(mesh_name)

    w = float(width_mm)
    h = float(height_mm)

    plane_u = str(plane).upper()
    if plane_u == "XZ":
        verts = [(0.0, 0.0, 0.0), (w, 0.0, 0.0), (w, 0.0, h), (0.0, 0.0, h)]
    elif plane_u == "YZ":
        verts = [(0.0, 0.0, 0.0), (0.0, w, 0.0), (0.0, w, h), (0.0, 0.0, h)]
    else:
        raise ValueError(f"Unknown plane {plane!r} (expected 'XZ' or 'YZ')")

    faces = [(0, 1, 2, 3)]
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    if flip_u:
        uvs = [(1.0 - u, v) for (u, v) in uvs]
    if flip_v:
        uvs = [(u, 1.0 - v) for (u, v) in uvs]
    _ensure_uv_layer(mesh, uvs)
    return mesh




def _make_center_plane_mesh(
    mesh_name: str,
    *,
    width_mm: float,
    height_mm: float,
    flip_u: bool,
    flip_v: bool,
) -> bpy.types.Mesh:
    """Create a single-quad plane *centered at the origin* in local XY (z=0).

    This is used for the optional schematics.center image, where the *image center*
    is placed on the Z axis at a chosen z_mm and the plane is oriented to be
    parallel to the isometric camera plane.
    """
    mesh = bpy.data.meshes.get(mesh_name)
    if mesh is None:
        mesh = bpy.data.meshes.new(mesh_name)

    w = float(width_mm)
    h = float(height_mm)
    hw = 0.5 * w
    hh = 0.5 * h

    verts = [(-hw, -hh, 0.0), (hw, -hh, 0.0), (hw, hh, 0.0), (-hw, hh, 0.0)]
    faces = [(0, 1, 2, 3)]

    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    if flip_u:
        uvs = [(1.0 - u, v) for (u, v) in uvs]
    if flip_v:
        uvs = [(u, 1.0 - v) for (u, v) in uvs]
    _ensure_uv_layer(mesh, uvs)
    return mesh

def create_schematic_plane(
    name: str,
    *,
    image_path: str,
    plane: str,
    height_mm: float,
    width_mm: Optional[float],
    scale: float,
    emission_strength: float,
    interpolation: str,
    flip_u: bool,
    flip_v: bool,
    parent_obj: Optional[bpy.types.Object],
    target_collection: bpy.types.Collection,
) -> Optional[bpy.types.Object]:
    if not image_path:
        warn(f"{name}: no image_path; skipping")
        return None
    if not os.path.exists(image_path):
        warn(f"{name}: image not found: {image_path}")
        return None

    try:
        img = bpy.data.images.load(image_path, check_existing=True)
    except Exception as e:
        warn(f"{name}: failed to load image {image_path}: {e!r}")
        return None

    px_w = float(getattr(img, "size", [0, 0])[0] or 0)
    px_h = float(getattr(img, "size", [0, 0])[1] or 0)
    if px_w <= 0 or px_h <= 0:
        px_w, px_h = 1.0, 1.0

    h_mm = float(height_mm) * float(scale)
    if width_mm is not None:
        w_mm = float(width_mm) * float(scale)
    else:
        aspect = px_w / px_h
        w_mm = h_mm * aspect

    mesh = _make_corner_plane_mesh(
        name + "_MESH",
        plane=plane,
        width_mm=w_mm,
        height_mm=h_mm,
        flip_u=bool(flip_u),
        flip_v=bool(flip_v),
    )

    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, mesh)
        try:
            target_collection.objects.link(obj)
        except Exception:
            bpy.context.scene.collection.objects.link(obj)
    else:
        obj.data = mesh

    move_object_to_collection(obj, target_collection)

    mat = ensure_material_image_emission(
        "MAT_" + name,
        image_path,
        emission_strength=float(emission_strength),
        interpolation=str(interpolation),
    )
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    # Make it "graphic" (not participating in lighting)
    try:
        obj.visible_shadow = False
    except Exception:
        pass
    try:
        obj.cycles_visibility.camera = True
        obj.cycles_visibility.diffuse = False
        obj.cycles_visibility.glossy = False
        obj.cycles_visibility.transmission = False
        obj.cycles_visibility.shadow = False
        obj.cycles_visibility.scatter = False
    except Exception:
        pass

    if parent_obj is not None:
        parent_keep_local(obj, parent_obj)

    return obj


# ----------------------------


# ----------------------------
# Center image plane (optional)
# ----------------------------

def _normalize_vec3_any(v: Any, *, fallback: Tuple[float, float, float] = (1.0, 1.0, 1.0)) -> Vector:
    """Best-effort conversion of an arbitrary value to a normalized Vector((x,y,z))."""
    try:
        if isinstance(v, Vector):
            vv = Vector(v)
        elif isinstance(v, (list, tuple)) and len(v) >= 3:
            vv = Vector((float(v[0]), float(v[1]), float(v[2])))
        else:
            vv = Vector((float(fallback[0]), float(fallback[1]), float(fallback[2])))
    except Exception:
        vv = Vector((float(fallback[0]), float(fallback[1]), float(fallback[2])))

    if vv.length < 1e-9:
        vv = Vector((float(fallback[0]), float(fallback[1]), float(fallback[2])))

    try:
        vv.normalize()
    except Exception:
        vv = Vector((float(fallback[0]), float(fallback[1]), float(fallback[2]))).normalized()
    return vv


def _camera_plane_basis(camera_direction: Any) -> Tuple[Vector, Vector, Vector]:
    """Return an orthonormal basis (x,y,n) for a plane parallel to the camera plane.

    - n: plane normal pointing *toward* the camera (camera at +direction, looking toward origin)
    - y: 'up' direction within the plane (world +Z projected into the plane), so the image stays upright
    - x: horizontal direction within the plane (top/bottom edges)
    """
    n = _normalize_vec3_any(camera_direction, fallback=(1.0, 1.0, 1.0))

    world_up = Vector((0.0, 0.0, 1.0))
    y = world_up - n * world_up.dot(n)
    if y.length < 1e-6:
        # If camera is too close to vertical, fall back to projecting world Y
        world_up = Vector((0.0, 1.0, 0.0))
        y = world_up - n * world_up.dot(n)
    if y.length < 1e-6:
        world_up = Vector((1.0, 0.0, 0.0))
        y = world_up - n * world_up.dot(n)

    if y.length < 1e-9:
        y = Vector((0.0, 0.0, 1.0))
    else:
        y.normalize()

    x = y.cross(n)
    if x.length < 1e-9:
        x = n.cross(y)
    if x.length < 1e-9:
        x = Vector((1.0, 0.0, 0.0))
    else:
        x.normalize()

    # Re-orthogonalize y to ensure a tight right-handed basis
    y = n.cross(x)
    if y.length > 1e-9:
        y.normalize()

    return (x, y, n)


def create_center_schematic_plane(
    name: str,
    *,
    image_path: str,
    z_mm: float,
    camera_direction: Any,
    height_mm: float,
    width_mm: Optional[float],
    scale: float,
    emission_strength: float,
    interpolation: str,
    flip_u: bool,
    flip_v: bool,
    parent_obj: Optional[bpy.types.Object],
    target_collection: bpy.types.Collection,
) -> Optional[bpy.types.Object]:
    """Create a centered image plane whose center lies on the Z axis at (0,0,z_mm).

    The plane is oriented to be parallel to the isometric camera plane (camera direction defaults to +[1,1,1]),
    and its top/bottom edges are aligned with the camera plane horizontal (45° between X and Y for the default camera).
    """
    if not image_path:
        warn(f"{name}: no image_path; skipping")
        return None
    if not os.path.exists(image_path):
        warn(f"{name}: image not found: {image_path}")
        return None

    try:
        img = bpy.data.images.load(image_path, check_existing=True)
    except Exception as e:
        warn(f"{name}: failed to load image {image_path}: {e!r}")
        return None

    px_w = float(getattr(img, "size", [0, 0])[0] or 0)
    px_h = float(getattr(img, "size", [0, 0])[1] or 0)
    if px_w <= 0 or px_h <= 0:
        px_w, px_h = 1.0, 1.0

    h_mm = float(height_mm) * float(scale)
    if width_mm is not None:
        w_mm = float(width_mm) * float(scale)
    else:
        aspect = px_w / px_h
        w_mm = h_mm * aspect

    mesh = _make_center_plane_mesh(
        name + "_MESH",
        width_mm=w_mm,
        height_mm=h_mm,
        flip_u=bool(flip_u),
        flip_v=bool(flip_v),
    )

    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, mesh)
        try:
            target_collection.objects.link(obj)
        except Exception:
            bpy.context.scene.collection.objects.link(obj)
    else:
        obj.data = mesh

    move_object_to_collection(obj, target_collection)

    # Parent first (so setting matrix_world computes the correct local matrix)
    if parent_obj is not None:
        parent_keep_local(obj, parent_obj)

    # Orient to camera plane and place center on Z axis
    x_axis, y_axis, n_axis = _camera_plane_basis(camera_direction)
    rot3 = Matrix((x_axis, y_axis, n_axis)).transposed()
    world = Matrix.Translation(Vector((0.0, 0.0, float(z_mm)))) @ rot3.to_4x4()
    try:
        obj.matrix_world = world
    except Exception:
        # Fallback: set via euler + location
        obj.location = Vector((0.0, 0.0, float(z_mm)))
        try:
            obj.rotation_euler = rot3.to_euler()
        except Exception:
            pass

    mat = ensure_material_image_emission(
        "MAT_" + name,
        image_path,
        emission_strength=float(emission_strength),
        interpolation=str(interpolation),
    )
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    # Make it "graphic" (not participating in lighting)
    try:
        obj.visible_shadow = False
    except Exception:
        pass
    try:
        obj.cycles_visibility.camera = True
        obj.cycles_visibility.diffuse = False
        obj.cycles_visibility.glossy = False
        obj.cycles_visibility.transmission = False
        obj.cycles_visibility.shadow = False
        obj.cycles_visibility.scatter = False
    except Exception:
        pass

    return obj

# External .blend collection import (robust)
# ----------------------------

@dataclass(frozen=True)
class BlendCollectionKey:
    blend_path: str
    collection_name: Optional[str]
    link: bool


_LOADED_COLLECTION_CACHE: Dict[BlendCollectionKey, bpy.types.Collection] = {}


def _list_collections_in_blend(blend_path: str, *, link: bool) -> List[str]:
    with bpy.data.libraries.load(blend_path, link=link) as (data_from, _data_to):
        return list(getattr(data_from, "collections", []))


def _load_collection_from_blend(blend_path: str, collection_name: str, *, link: bool) -> Optional[bpy.types.Collection]:
    with bpy.data.libraries.load(blend_path, link=link) as (data_from, data_to):
        if collection_name not in getattr(data_from, "collections", []):
            return None
        data_to.collections = [collection_name]
    if not data_to.collections:
        return None
    return data_to.collections[0]


def load_collection_from_blend(
    blend_path: str,
    *,
    collection_name: Optional[str],
    link: bool,
    fallback_names: Sequence[str] = (),
) -> Optional[bpy.types.Collection]:
    """Load a Collection datablock from an external .blend.

    Robust behavior:
    - Missing file -> warn + None
    - Missing collection -> try fallbacks, then any EXPORT_*, then "Collection", then anything.
    """
    blend_path = str(Path(blend_path).resolve())

    if not os.path.exists(blend_path):
        warn(f"Blend file not found: {blend_path}")
        return None

    key = BlendCollectionKey(blend_path=blend_path, collection_name=collection_name, link=bool(link))
    if key in _LOADED_COLLECTION_CACHE:
        return _LOADED_COLLECTION_CACHE[key]

    try:
        available = _list_collections_in_blend(blend_path, link=link)
    except Exception as e:
        warn(f"Failed to read collections from {blend_path}: {e!r}")
        return None

    if not available:
        warn(f"No collections found in blend library: {blend_path}")
        return None

    candidates: List[str] = []
    if collection_name:
        candidates.append(str(collection_name))
    for n in fallback_names:
        if n:
            candidates.append(str(n))

    export_like = [n for n in available if n.startswith("EXPORT_")]
    for n in sorted(export_like):
        if n not in candidates:
            candidates.append(n)

    if "Collection" in available and "Collection" not in candidates:
        candidates.append("Collection")

    for n in available:
        if n not in candidates:
            candidates.append(n)

    picked: Optional[bpy.types.Collection] = None
    picked_name: Optional[str] = None

    for cand in candidates:
        coll = None
        try:
            coll = _load_collection_from_blend(blend_path, cand, link=link)
        except Exception as e:
            warn(f"Error loading collection {cand!r} from {blend_path}: {e!r}")
            coll = None

        if coll is None:
            continue

        # Prefer non-empty collections
        try:
            n_objs = len(getattr(coll, "all_objects", []))
        except Exception:
            n_objs = 0

        picked = coll
        picked_name = cand
        if n_objs > 0:
            break

    if picked is None:
        warn(f"Could not load any collection from {blend_path}. Requested={collection_name!r}.")
        return None

    info(f"Loaded collection '{picked.name}' (picked='{picked_name}', requested='{collection_name}') from: {blend_path}")
    _LOADED_COLLECTION_CACHE[key] = picked
    return picked


# ----------------------------
# Pivot/anchor evaluation utilities
# ----------------------------

_SUFFIX_RE = re.compile(r"\.\d+$")


def base_name(name: str) -> str:
    return _SUFFIX_RE.sub("", name or "")


def _find_object_by_base_name(objs: Sequence[bpy.types.Object], desired: str) -> Optional[bpy.types.Object]:
    if not desired:
        return None
    desired_b = base_name(desired)
    desired_l = desired_b.lower()

    for o in objs:
        if o.name == desired:
            return o
    for o in objs:
        if base_name(o.name) == desired_b:
            return o
    for o in objs:
        if base_name(o.name).lower() == desired_l:
            return o
    return None


def _object_is_in_rig_collection(obj: bpy.types.Object) -> bool:
    try:
        return any(c.name.startswith("RIG_") for c in obj.users_collection)
    except Exception:
        return False


def _score_anchor_candidate(obj: bpy.types.Object) -> int:
    b = base_name(obj.name)
    s = 0
    if obj.type == "EMPTY":
        s += 5
    if _object_is_in_rig_collection(obj):
        s += 100
    if b.startswith("RIG_"):
        s += 20
    if b.endswith("_ROOT"):
        s += 60
    if "ROOT" in b:
        s += 30
    if b == "RIG_STAGE_ROOT":
        s += 200
    if b == "RIG_JOYSTICK_ROOT":
        s += 180
    if b.startswith("RIG_PCB_G_"):
        s += 150
    if b.startswith("RIG_PCB_ROOT"):
        s += 160
    return s


class _TempCollectionLink:
    """Temporarily link a collection into the scene so object world matrices are evaluated.

    Creates a hidden helper collection, links `coll` as a child, updates depsgraph, yields depsgraph.
    On exit, unlinks and deletes the helper collection (leaving no extra objects/planes in the final file).
    """
    def __init__(self, coll: bpy.types.Collection):
        self.coll = coll
        self.helper: Optional[bpy.types.Collection] = None
        self.did_link_child: bool = False
        self.did_link_helper: bool = False
        self.depsgraph = None

    def __enter__(self):
        scene = bpy.context.scene
        helper = bpy.data.collections.new("__TMP_EVAL__")
        self.helper = helper

        # Link helper into scene
        try:
            scene.collection.children.link(helper)
            self.did_link_helper = True
        except Exception:
            self.did_link_helper = False

        try:
            helper.hide_viewport = True
        except Exception:
            pass
        try:
            helper.hide_render = True
        except Exception:
            pass

        # Link the target collection under the helper
        try:
            helper.children.link(self.coll)
            self.did_link_child = True
        except Exception:
            # If already linked elsewhere, we may still be able to evaluate.
            self.did_link_child = False

        # Force update
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass

        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            depsgraph.update()
            self.depsgraph = depsgraph
        except Exception:
            self.depsgraph = None

        return self.depsgraph

    def __exit__(self, exc_type, exc, tb):
        scene = bpy.context.scene

        # Unlink child collection
        if self.helper is not None and self.did_link_child:
            try:
                self.helper.children.unlink(self.coll)
            except Exception:
                pass

        # Unlink helper from scene
        if self.helper is not None and self.did_link_helper:
            try:
                scene.collection.children.unlink(self.helper)
            except Exception:
                pass

        # Remove helper datablock
        if self.helper is not None:
            try:
                bpy.data.collections.remove(self.helper)
            except Exception:
                pass


def _eval_translation(obj: bpy.types.Object, depsgraph) -> Vector:
    if depsgraph is not None:
        try:
            obj_eval = obj.evaluated_get(depsgraph)
            return obj_eval.matrix_world.to_translation().copy()
        except Exception:
            pass
    try:
        return obj.matrix_world.to_translation().copy()
    except Exception:
        return Vector((0.0, 0.0, 0.0))


def compute_collection_bbox_eval(coll: bpy.types.Collection, depsgraph) -> Optional[Tuple[Vector, Vector]]:
    bb_min = Vector((float("inf"), float("inf"), float("inf")))
    bb_max = Vector((-float("inf"), -float("inf"), -float("inf")))
    found = False

    try:
        objs = list(coll.all_objects)
    except Exception:
        objs = []

    for obj in objs:
        if obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            continue
        try:
            corners = obj.bound_box
        except Exception:
            corners = None
        if not corners:
            continue

        # Evaluated matrix_world (requires collection linked into scene)
        if depsgraph is not None:
            try:
                mw = obj.evaluated_get(depsgraph).matrix_world
            except Exception:
                mw = obj.matrix_world
        else:
            mw = obj.matrix_world

        for c in corners:
            v = mw @ Vector((c[0], c[1], c[2]))
            bb_min.x = min(bb_min.x, v.x)
            bb_min.y = min(bb_min.y, v.y)
            bb_min.z = min(bb_min.z, v.z)
            bb_max.x = max(bb_max.x, v.x)
            bb_max.y = max(bb_max.y, v.y)
            bb_max.z = max(bb_max.z, v.z)
            found = True

    if not found:
        return None
    return bb_min, bb_max


def choose_anchor_offset(
    coll: bpy.types.Collection,
    *,
    spec: Dict[str, Any],
    debug: bool = False,
) -> Tuple[Vector, str]:
    """Return (anchor_offset, reason_string) in *collection/world* coordinates (collection linked at origin).

    This function temporarily links the collection into a hidden helper in the scene so matrices are valid.
    """
    pivot_mode = str(spec.get("pivot_mode") or spec.get("anchor_mode") or spec.get("pivot") or "AUTO").upper()
    anchor_name = spec.get("anchor_object") or spec.get("pivot_object") or spec.get("anchor")

    # aliases
    if pivot_mode == "CENTER":
        pivot_mode = "BBOX_CENTER"
    if pivot_mode == "MIN":
        pivot_mode = "BBOX_MIN"

    try:
        objs = list(coll.all_objects)
    except Exception:
        objs = []
    if not objs:
        # fallback: collection.objects
        try:
            objs = list(coll.objects)
        except Exception:
            objs = []

    # Candidate selection (by name/type) can happen without evaluation.
    explicit_obj = None
    if anchor_name:
        explicit_obj = _find_object_by_base_name(objs, str(anchor_name))
        if explicit_obj is None:
            # last-resort: search global datablocks by base-name
            desired_b = base_name(str(anchor_name))
            for o in bpy.data.objects:
                if base_name(o.name) == desired_b:
                    explicit_obj = o
                    break

    # Pre-pick rig-ish empty for AUTO/RIG_ROOT to avoid scoring inside eval context.
    rig_best = None
    empties = [o for o in objs if getattr(o, "type", None) == "EMPTY"]
    if empties:
        rig_best = max(empties, key=_score_anchor_candidate)

    # Evaluate transforms within a temp scene link
    with _TempCollectionLink(coll) as depsgraph:
        # 1) OBJECT
        if pivot_mode == "OBJECT":
            if explicit_obj is None:
                return Vector((0.0, 0.0, 0.0)), f"pivot_mode=OBJECT but anchor_object '{anchor_name}' not found; using ORIGIN"
            v = _eval_translation(explicit_obj, depsgraph)
            return v, f"OBJECT:{explicit_obj.name}"

        # 2) ORIGIN
        if pivot_mode == "ORIGIN":
            return Vector((0.0, 0.0, 0.0)), "ORIGIN"

        # 3) BBOX modes
        if pivot_mode in {"BBOX_CENTER", "BBOX_MIN"}:
            bb = compute_collection_bbox_eval(coll, depsgraph)
            if bb is None:
                return Vector((0.0, 0.0, 0.0)), f"{pivot_mode} bbox missing; using ORIGIN"
            bb_min, bb_max = bb
            if pivot_mode == "BBOX_MIN":
                return bb_min.copy(), "BBOX_MIN"
            return ((bb_min + bb_max) * 0.5).copy(), "BBOX_CENTER"

        # 4) RIG_ROOT
        if pivot_mode == "RIG_ROOT":
            if explicit_obj is not None:
                v = _eval_translation(explicit_obj, depsgraph)
                return v, f"RIG_ROOT explicit:{explicit_obj.name}"
            if rig_best is not None and _score_anchor_candidate(rig_best) > 0:
                v = _eval_translation(rig_best, depsgraph)
                return v, f"RIG_ROOT auto:{rig_best.name}"
            return Vector((0.0, 0.0, 0.0)), "RIG_ROOT not found; using ORIGIN"

        # 5) AUTO
        if explicit_obj is not None:
            v = _eval_translation(explicit_obj, depsgraph)
            return v, f"AUTO explicit:{explicit_obj.name}"
        if rig_best is not None and _score_anchor_candidate(rig_best) >= 100:
            v = _eval_translation(rig_best, depsgraph)
            return v, f"AUTO rig:{rig_best.name}"

        bb = compute_collection_bbox_eval(coll, depsgraph)
        if bb is not None:
            bb_min, bb_max = bb
            return ((bb_min + bb_max) * 0.5).copy(), "AUTO bbox_center"

    return Vector((0.0, 0.0, 0.0)), "AUTO origin"


# ----------------------------
# Component instancing (pivot compensated)
# ----------------------------

def ensure_instance_empty(name: str, *, collection: bpy.types.Collection, target_collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, None)
        try:
            target_collection.objects.link(obj)
        except Exception:
            bpy.context.scene.collection.objects.link(obj)
    move_object_to_collection(obj, target_collection)
    obj.empty_display_type = "PLAIN_AXES"
    obj.instance_type = "COLLECTION"
    obj.instance_collection = collection
    return obj


def _as_scale_vec(scale: Union[float, Sequence[float]]) -> Vector:
    if isinstance(scale, (int, float)):
        return Vector((float(scale), float(scale), float(scale)))
    sc = list(scale)
    if len(sc) != 3:
        sc = [1.0, 1.0, 1.0]
    return Vector((float(sc[0]), float(sc[1]), float(sc[2])))


def _find_dupli_anchor_world(inst_obj: bpy.types.Object, anchor_name: str) -> Optional[Vector]:
    """Best-effort: find world location of an object inside a collection instance via depsgraph.

    Notes:
    - For collection instances, the duplicated objects are not real scene objects.
      They appear as entries in `depsgraph.object_instances`.
    - Depending on Blender visibility settings, some objects (especially hidden rig empties)
      may not appear here. In that case this function returns None.
    """
    desired = base_name(anchor_name or "")
    if not desired:
        return None

    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
    except Exception:
        return None

    # `depsgraph.object_instances[*].instance_object` might reference the *original*
    # instancer object, not the evaluated one (varies by Blender version/settings).
    inst_base_names = {base_name(getattr(inst_obj, "name", ""))}
    inst_ids = {inst_obj}
    try:
        inst_eval = inst_obj.evaluated_get(depsgraph)
        inst_ids.add(inst_eval)
        inst_base_names.add(base_name(getattr(inst_eval, "name", "")))
    except Exception:
        inst_eval = None

    def _is_this_instancer(candidate: Optional[bpy.types.Object]) -> bool:
        if candidate is None:
            return False
        if candidate in inst_ids:
            return True
        return base_name(getattr(candidate, "name", "")) in inst_base_names

    try:
        for oi in depsgraph.object_instances:
            if not getattr(oi, "is_instance", False):
                continue

            instancer = getattr(oi, "instance_object", None)
            parent = getattr(oi, "parent", None)

            if not (_is_this_instancer(instancer) or _is_this_instancer(parent)):
                continue

            obj = getattr(oi, "object", None)
            if obj is None:
                continue
            if base_name(obj.name) == desired:
                try:
                    return oi.matrix_world.to_translation().copy()
                except Exception:
                    return Vector((oi.matrix_world[0][3], oi.matrix_world[1][3], oi.matrix_world[2][3]))
    except Exception:
        return None

    return None


def instance_collection_pivoted(
    slot_name: str,
    *,
    collection: bpy.types.Collection,
    location_mm: Sequence[float],
    rotation_deg: Sequence[float],
    scale: Union[float, Sequence[float]],
    parent_obj: Optional[bpy.types.Object],
    target_collection: bpy.types.Collection,
    spec: Dict[str, Any],
    debug: bool = False,
) -> None:
    """Create an instance with transform order:

        world = T(location) * R(rotation) * S(scale) * T(-anchor_offset) * content

    Implemented as a stable empty chain:
      parent_obj
        └── PIV_<slot>   (location)
              └── ROT_<slot>   (rotation + scale)
                    └── OFF_<slot>   (translate -anchor_offset)
                          └── INST_<slot>  (collection instance at origin)
    """
    loc = Vector((float(location_mm[0]), float(location_mm[1]), float(location_mm[2])))

    rot_deg = [float(rotation_deg[0]), float(rotation_deg[1]), float(rotation_deg[2])]
    rot_eul = Euler((math.radians(rot_deg[0]), math.radians(rot_deg[1]), math.radians(rot_deg[2])), "XYZ")
    svec = _as_scale_vec(scale)

    anchor_offset, anchor_reason = choose_anchor_offset(collection, spec=spec, debug=debug)
    if debug:
        info(f"{slot_name}: anchor_offset={tuple(round(v, 4) for v in anchor_offset)} ({anchor_reason})")

    piv = ensure_empty_obj(f"PIV_{slot_name}", target_collection=target_collection)
    rot = ensure_empty_obj(f"ROT_{slot_name}", target_collection=target_collection)
    off = ensure_empty_obj(f"OFF_{slot_name}", target_collection=target_collection)
    inst = ensure_instance_empty(f"INST_{slot_name}", collection=collection, target_collection=target_collection)

    parent_keep_local(piv, parent_obj)
    parent_keep_local(rot, piv)
    parent_keep_local(off, rot)
    parent_keep_local(inst, off)

    # Local transforms
    piv.location = loc
    piv.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    piv.scale = Vector((1.0, 1.0, 1.0))

    rot.location = Vector((0.0, 0.0, 0.0))
    rot.rotation_euler = rot_eul
    rot.scale = svec

    off.location = -anchor_offset
    off.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    off.scale = Vector((1.0, 1.0, 1.0))

    inst.location = Vector((0.0, 0.0, 0.0))
    inst.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    inst.scale = Vector((1.0, 1.0, 1.0))

    # Optional: verify anchor ends up at loc (only possible if anchor_object provided).
    if debug and spec.get("anchor_object"):
        anchor_world = _find_dupli_anchor_world(inst, str(spec.get("anchor_object")))
        if anchor_world is not None:
            delta = anchor_world - piv.matrix_world.to_translation()
            info(f"{slot_name}: dupli anchor world={tuple(round(v, 4) for v in anchor_world)}, "
                 f"target={tuple(round(v, 4) for v in piv.matrix_world.to_translation())}, "
                 f"delta={tuple(round(v, 4) for v in delta)}")
        else:
            info(f"{slot_name}: (debug) could not locate dupli anchor '{spec.get('anchor_object')}' inside instance")


# ----------------------------
# Build
# ----------------------------

def build_scene(
    cfg: Dict[str, Any],
    manifest_path: str,
    *,
    output_override: Optional[str],
    no_pack_images: bool,
    debug: bool,
) -> str:
    out_cfg = cfg.get("output", {}) if isinstance(cfg.get("output", {}), dict) else {}
    export_collection_name = str(out_cfg.get("export_collection", "EXPORT_electrical_mechanical"))
    out_blend_rel = out_cfg.get("blend_path", "assets/compiled/blend/electrical_mechanical.blend")

    out_path = output_override or out_blend_rel
    out_abs = Path(abspath_from_manifest(manifest_path, out_path)).resolve()
    out_abs.parent.mkdir(parents=True, exist_ok=True)

    export_col = ensure_collection(export_collection_name)
    src_col = ensure_collection("SRC_electrical_mechanical", parent=export_col)
    rig_col = ensure_collection("RIG_electrical_mechanical", parent=export_col)

    schem_subcol = ensure_collection("SCHEMATICS", parent=src_col)
    comp_subcol = ensure_collection("COMPONENTS", parent=src_col)

    rig_root = ensure_empty_obj("RIG_ELECTRO_MECH_ROOT", target_collection=rig_col)
    rig_root.location = Vector((0.0, 0.0, 0.0))
    rig_root.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    rig_root.scale = Vector((1.0, 1.0, 1.0))

    # ----------------
    # Schematics
    # ----------------
    schem_cfg = cfg.get("schematics", {}) if isinstance(cfg.get("schematics", {}), dict) else {}
    schem_defaults = schem_cfg.get("defaults", {}) if isinstance(schem_cfg.get("defaults", {}), dict) else {}

    for side_key, default_plane in (("left", "XZ"), ("right", "YZ")):
        side_cfg = schem_cfg.get(side_key, {}) if isinstance(schem_cfg.get(side_key, {}), dict) else {}
        merged = merged_dict(schem_defaults, side_cfg)

        if not merged.get("enabled", True):
            info(f"schematics.{side_key}: disabled")
            continue

        plane = str(merged.get("plane", default_plane)).upper()

        img_rel = merged.get("image_path") or merged.get("png") or merged.get("image")
        if not img_rel:
            warn(f"schematics.{side_key}: missing image_path")
            continue
        img_abs = abspath_from_manifest(manifest_path, str(img_rel))

        size_mm = merged.get("size_mm", None)
        width_mm: Optional[float] = None
        height_mm: float = float(merged.get("height_mm", 300.0))
        if isinstance(size_mm, (list, tuple)) and len(size_mm) == 2:
            width_mm = float(size_mm[0])
            height_mm = float(size_mm[1])
        else:
            if "width_mm" in merged:
                try:
                    width_mm = float(merged.get("width_mm"))
                except Exception:
                    width_mm = None

        create_schematic_plane(
            f"SCHEM_{side_key.upper()}",
            image_path=img_abs,
            plane=plane,
            height_mm=height_mm,
            width_mm=width_mm,
            scale=float(merged.get("scale", 1.0)),
            emission_strength=float(merged.get("emission_strength", 1.0)),
            interpolation=str(merged.get("interpolation", "Cubic")),
            flip_u=bool(merged.get("flip_u", False)),
            flip_v=bool(merged.get("flip_v", False)),
            parent_obj=rig_root,
            target_collection=schem_subcol,
        )


    # Optional center schematic (billboard aligned to the camera plane)
    center_cfg = schem_cfg.get("center", {}) if isinstance(schem_cfg.get("center", {}), dict) else {}
    if center_cfg:
        merged_c = merged_dict(schem_defaults, center_cfg)

        if not merged_c.get("enabled", True):
            info("schematics.center: disabled")
        else:
            img_rel_c = merged_c.get("image_path") or merged_c.get("png") or merged_c.get("image")
            if not img_rel_c:
                warn("schematics.center: missing image_path")
            else:
                img_abs_c = abspath_from_manifest(manifest_path, str(img_rel_c))

                size_mm_c = merged_c.get("size_mm", None)
                width_mm_c: Optional[float] = None
                height_mm_c: float = float(merged_c.get("height_mm", schem_defaults.get("height_mm", 300.0) if isinstance(schem_defaults, dict) else 300.0))
                if isinstance(size_mm_c, (list, tuple)) and len(size_mm_c) == 2:
                    width_mm_c = float(size_mm_c[0])
                    height_mm_c = float(size_mm_c[1])
                else:
                    if "width_mm" in merged_c:
                        try:
                            width_mm_c = float(merged_c.get("width_mm"))
                        except Exception:
                            width_mm_c = None

                z_mm = float(merged_c.get("z_mm", 0.0))
                # Accept a few aliases
                for kz in ("z_location_mm", "z_loc_mm", "z"):
                    if kz in merged_c and merged_c.get(kz) is not None:
                        try:
                            z_mm = float(merged_c.get(kz))
                        except Exception:
                            pass
                        break

                cam_dir = merged_c.get("camera_direction", None)
                if cam_dir is None:
                    prev = cfg.get("preview_camera", {}) if isinstance(cfg.get("preview_camera", {}), dict) else {}
                    cam_dir = prev.get("direction", [1.0, 1.0, 1.0])

                create_center_schematic_plane(
                    "SCHEM_CENTER",
                    image_path=img_abs_c,
                    z_mm=z_mm,
                    camera_direction=cam_dir,
                    height_mm=height_mm_c,
                    width_mm=width_mm_c,
                    scale=float(merged_c.get("scale", 1.0)),
                    emission_strength=float(merged_c.get("emission_strength", 1.0)),
                    interpolation=str(merged_c.get("interpolation", "Cubic")),
                    flip_u=bool(merged_c.get("flip_u", False)),
                    flip_v=bool(merged_c.get("flip_v", False)),
                    parent_obj=rig_root,
                    target_collection=schem_subcol,
                )


    # ----------------
    # Components
    # ----------------
    comp_cfg = cfg.get("components", {}) if isinstance(cfg.get("components", {}), dict) else {}
    comp_defaults = comp_cfg.get("defaults", {}) if isinstance(comp_cfg.get("defaults", {}), dict) else {}

    def build_component(slot_name: str, spec: Dict[str, Any]) -> None:
        merged = merged_dict(comp_defaults, spec)
        if not merged.get("enabled", True):
            info(f"components.{slot_name}: disabled")
            return

        blend_rel = merged.get("blend") or merged.get("filepath") or merged.get("path")
        if not blend_rel:
            warn(f"components.{slot_name}: missing blend path; skipping")
            return
        blend_abs = abspath_from_manifest(manifest_path, str(blend_rel))

        coll_name = merged.get("blend_collection") or merged.get("collection")
        if coll_name is None:
            warn(f"components.{slot_name}: missing blend_collection; will fall back to first EXPORT_*")

        link = bool(merged.get("link", True))

        fallback_names: List[str] = []
        if isinstance(coll_name, str) and coll_name and not coll_name.startswith("EXPORT_"):
            fallback_names.append("EXPORT_" + coll_name)
        fallback_names.append("Collection")

        coll = load_collection_from_blend(
            blend_abs,
            collection_name=str(coll_name) if coll_name is not None else None,
            link=link,
            fallback_names=fallback_names,
        )
        if coll is None:
            warn(f"components.{slot_name}: could not load collection from {blend_abs}")
            return

        loc = merged.get("location_mm", [0.0, 0.0, 0.0])
        rot = parse_rotation_deg(merged, default=parse_rotation_deg(comp_defaults))
        sc = merged.get("scale", 1.0)

        instance_collection_pivoted(
            slot_name,
            collection=coll,
            location_mm=loc,
            rotation_deg=rot,
            scale=sc,
            parent_obj=rig_root,
            target_collection=comp_subcol,
            spec=merged,
            debug=debug,
        )

    for side in ("left", "right"):
        side_block = comp_cfg.get(side, {}) if isinstance(comp_cfg.get(side, {}), dict) else {}
        for kind in ("electrical", "mechanical"):
            spec = side_block.get(kind, {}) if isinstance(side_block.get(kind, {}), dict) else {}
            if not spec:
                continue
            build_component(f"{side}_{kind}", spec)

    # ----------------
    # No camera is created. Remove any cameras defensively.
    # ----------------
    delete_scene_objects_of_type("CAMERA")

    # ----------------
    # Pack images (optional)
    # ----------------
    pack_images = bool(out_cfg.get("pack_images", False)) and (not no_pack_images)
    if pack_images:
        try:
            bpy.ops.file.pack_all()
            info("Packed external files (images)")
        except Exception as e:
            warn(f"Failed to pack images: {e!r}")

    compress = bool(out_cfg.get("compress", True))
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(out_abs), compress=compress)
    except TypeError:
        bpy.ops.wm.save_as_mainfile(filepath=str(out_abs))

    info(f"Wrote blend: {out_abs}")
    return str(out_abs)


def main() -> None:
    args = parse_args()

    manifest_path = str(Path(args.manifest).resolve())
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    if not args.no_reset:
        reset_to_empty_file()

    cfg = load_json(manifest_path)
    apply_units(cfg)

    build_scene(
        cfg,
        manifest_path,
        output_override=args.output,
        no_pack_images=args.no_pack_images,
        debug=bool(args.debug),
    )


if __name__ == "__main__":
    main()
