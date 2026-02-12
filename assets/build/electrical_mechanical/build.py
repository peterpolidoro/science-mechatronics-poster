"""assets/build/electrical_mechanical/build.py

Build a reusable "electrical-mechanical corner" .blend asset for the poster.

Key features:
- Uses *PNG* schematics (image planes), not SVG.
- Places one schematic on the XZ plane and one on the YZ plane.
  - In both cases, the *min corner* of the image plane coincides with (0,0,0)
    and the plane grows into +X/+Z or +Y/+Z.
- Optionally instances up to 4 collections from external .blend files on the XY plane:
  - left electrical + left mechanical
  - right electrical + right mechanical
- Robust to missing/disabled assets in the manifest: warnings are printed and
  the build continues.

Run (from repo root):

  blender -b --factory-startup --python assets/build/electrical_mechanical/build.py -- \
    assets/build/electrical_mechanical/manifest.json

"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import bpy
from mathutils import Euler, Vector


# ----------------------------
# CLI helpers
# ----------------------------

def argv_after_dashes() -> List[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build an electrical-mechanical corner .blend from manifest")
    p.add_argument("manifest", help="Path to assets/build/electrical_mechanical/manifest.json")
    p.add_argument(
        "--output",
        default=None,
        help="Optional override for output .blend path (otherwise uses manifest['output']['blend_path'])",
    )
    p.add_argument(
        "--no-pack-images",
        action="store_true",
        help="Disable packing images even if manifest output.pack_images=true",
    )
    p.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not reset Blender to an empty file at start (advanced/debug).",
    )
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

    We expect this builder manifest lives at:
      <repo>/assets/build/electrical_mechanical/manifest.json

    So repo root is 3 parents up from manifest dir.

    If the structure is different, we fall back to walking upwards and
    picking the first parent that contains an "assets" dir.
    """
    mp = manifest_path.resolve()
    # Common case
    try:
        cand = mp.parent.parent.parent.parent
        if (cand / "assets").exists():
            return cand
    except Exception:
        pass

    # Fallback: walk up until we find an assets/ directory
    for parent in mp.parents:
        if (parent / "assets").exists():
            return parent
    return mp.parent


def abspath_from_manifest(manifest_path: str | Path, maybe_rel: str | Path) -> str:
    """Resolve a path referenced by the manifest.

    - Absolute paths are returned as-is.
    - Relative paths are tried against:
        1) manifest directory
        2) manifest parent directory
        3) manifest grandparent directory
        4) repo root (best-effort)

    Returns the *best candidate*, even if it doesn't exist.
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

    # If nothing exists yet (common for output paths), prefer repo-root-relative.
    try:
        return str((repo_root / p).resolve())
    except Exception:
        return str((mp.parent / p).resolve())


def merged_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow merge base + override."""
    out = dict(base) if isinstance(base, dict) else {}
    if isinstance(override, dict):
        out.update(override)
    return out


# ----------------------------
# Scene + collection utilities
# ----------------------------

def reset_to_empty_file() -> None:
    """Reset Blender to a known-empty state."""
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    except Exception as e:
        warn(f"Could not read_factory_settings(use_empty=True): {e!r}")


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
        scene.unit_settings.scale_length = float(u.get("scale_length", 0.001))
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


def ensure_empty(name: str, *, location_mm: Sequence[float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = "PLAIN_AXES"
        bpy.context.scene.collection.objects.link(obj)
    obj.location = Vector([float(location_mm[0]), float(location_mm[1]), float(location_mm[2])])
    return obj


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


# ----------------------------
# Materials (PNG schematics)
# ----------------------------

def _set_material_transparency(mat: bpy.types.Material, *, method: str = "BLENDED") -> None:
    """Handle Blender 4/5 transparency APIs with fallbacks."""
    m = str(method).upper()
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = m  # 'OPAQUE','DITHERED','BLENDED','CLIP'
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

    # Clear nodes for deterministic rebuild
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

    # Texture filtering
    try:
        tex.interpolation = str(interpolation)
    except Exception:
        pass

    # Alpha handling
    try:
        img.alpha_mode = "STRAIGHT"
    except Exception:
        pass

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (-220, 60)
    emission.inputs["Strength"].default_value = float(emission_strength)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (-220, -140)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (140, 0)

    # Explicitly use UVs
    if "UV" in texcoord.outputs and "Vector" in tex.inputs:
        links.new(texcoord.outputs["UV"], tex.inputs["Vector"])

    links.new(tex.outputs["Color"], emission.inputs["Color"])

    # Use alpha to mix transparent vs emission
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

    # For a single-quad plane, we expect 4 loops
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
    """Create a plane mesh with one corner at the origin.

    - plane="XZ": vertices span +X and +Z at y=0
    - plane="YZ": vertices span +Y and +Z at x=0
    """
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

    # UVs: map origin corner -> (0,0)
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
    """Create a schematic image plane. Returns the created object, or None if missing."""

    if not image_path:
        warn(f"{name}: no image_path specified; skipping")
        return None

    if not os.path.exists(image_path):
        warn(f"{name}: image not found: {image_path}")
        return None

    # Load image to compute aspect ratio (and for material)
    try:
        img = bpy.data.images.load(image_path, check_existing=True)
    except Exception as e:
        warn(f"{name}: failed to load image {image_path}: {e!r}")
        return None

    px_w = float(getattr(img, "size", [0, 0])[0] or 0)
    px_h = float(getattr(img, "size", [0, 0])[1] or 0)
    if px_w <= 0 or px_h <= 0:
        warn(f"{name}: image has invalid size; using square fallback")
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
        bpy.context.scene.collection.objects.link(obj)
    else:
        obj.data = mesh

    # Material
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

    # Keep schematic planes "graphic" like (no shadows/reflections)
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

    # Parenting + collection
    if parent_obj is not None:
        obj.parent = parent_obj
        try:
            obj.matrix_parent_inverse = parent_obj.matrix_world.inverted()
        except Exception:
            pass

    move_object_to_collection(obj, target_collection)
    return obj


# ----------------------------
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
    """Load a Collection datablock from an external .blend file.

    - If the file doesn't exist: returns None.
    - If the requested collection isn't found: tries fallbacks and then EXPORT_* collections.
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

    # Blender's default collection name
    if "Collection" in available and "Collection" not in candidates:
        candidates.append("Collection")

    # Anything else
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

        # Prefer non-empty
        n_objs = 0
        try:
            n_objs = len(getattr(coll, "all_objects", []))
        except Exception:
            n_objs = 0

        picked = coll
        picked_name = cand
        if n_objs > 0:
            break

    if picked is None:
        warn(
            "Could not load any collection from blend. "
            f"Requested={collection_name!r}. Available={available[:20]}{'...' if len(available) > 20 else ''}"
        )
        return None

    info(f"Loaded collection '{picked.name}' (picked='{picked_name}', requested='{collection_name}') from: {blend_path}")
    _LOADED_COLLECTION_CACHE[key] = picked
    return picked


def instance_collection(
    name: str,
    *,
    collection: bpy.types.Collection,
    location_mm: Sequence[float],
    rotation_deg: Sequence[float],
    scale: Union[float, Sequence[float]],
    parent_obj: Optional[bpy.types.Object],
    target_collection: bpy.types.Collection,
) -> bpy.types.Object:
    """Instance a collection via an Empty object."""
    inst = bpy.data.objects.get(name)
    if inst is None:
        inst = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(inst)

    inst.empty_display_type = "PLAIN_AXES"
    inst.instance_type = "COLLECTION"
    inst.instance_collection = collection

    if parent_obj is not None:
        inst.parent = parent_obj
        try:
            inst.matrix_parent_inverse = parent_obj.matrix_world.inverted()
        except Exception:
            pass

    # Transform
    inst.location = Vector([float(location_mm[0]), float(location_mm[1]), float(location_mm[2])])
    inst.rotation_euler = Euler([math.radians(float(v)) for v in rotation_deg], "XYZ")

    if isinstance(scale, (int, float)):
        s = float(scale)
        inst.scale = Vector((s, s, s))
    else:
        sc = list(scale)
        if len(sc) != 3:
            sc = [1.0, 1.0, 1.0]
        inst.scale = Vector((float(sc[0]), float(sc[1]), float(sc[2])))

    move_object_to_collection(inst, target_collection)
    return inst


# ----------------------------
# Preview camera
# ----------------------------

def ensure_camera(name: str) -> bpy.types.Object:
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam_data = bpy.data.cameras.new(name + "_DATA")
        cam = bpy.data.objects.new(name, cam_data)
        bpy.context.scene.collection.objects.link(cam)
    return cam


def point_camera_at(cam_obj: bpy.types.Object, target_mm: Sequence[float]) -> None:
    tgt = Vector([float(target_mm[0]), float(target_mm[1]), float(target_mm[2])])
    direction = tgt - cam_obj.location
    if direction.length < 1e-9:
        return
    # Blender cameras look down local -Z, with local Y as up
    try:
        rot_quat = direction.to_track_quat("-Z", "Y")
        cam_obj.rotation_euler = rot_quat.to_euler()
    except Exception:
        pass


# ----------------------------
# Build
# ----------------------------

def build_scene(cfg: Dict[str, Any], manifest_path: str, *, output_override: Optional[str], no_pack_images: bool) -> str:
    out_cfg = cfg.get("output", {}) if isinstance(cfg.get("output", {}), dict) else {}

    export_collection_name = str(out_cfg.get("export_collection", "EXPORT_electrical_mechanical"))
    out_blend_rel = out_cfg.get("blend_path", "assets/compiled/blend/electrical_mechanical.blend")

    out_path = output_override or out_blend_rel
    out_abs = Path(abspath_from_manifest(manifest_path, out_path)).resolve()
    out_abs.parent.mkdir(parents=True, exist_ok=True)

    # Collections
    export_col = ensure_collection(export_collection_name)
    src_col = ensure_collection("SRC_electrical_mechanical", parent=export_col)
    rig_col = ensure_collection("RIG_electrical_mechanical", parent=export_col)

    # Organize within SRC
    schem_subcol = ensure_collection("SCHEMATICS", parent=src_col)
    comp_subcol = ensure_collection("COMPONENTS", parent=src_col)

    # Root rig empty
    rig_root = ensure_empty("RIG_ELECTRO_MECH_ROOT", location_mm=(0.0, 0.0, 0.0))
    move_object_to_collection(rig_root, rig_col)

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

        # Size controls
        size_mm = merged.get("size_mm", None)
        width_mm: Optional[float] = None
        height_mm: float = float(merged.get("height_mm", 300.0))
        if isinstance(size_mm, (list, tuple)) and len(size_mm) == 2:
            width_mm = float(size_mm[0])
            height_mm = float(size_mm[1])
        else:
            # Optional override: width_mm
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

    # ----------------
    # Components (optional)
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
            warn(f"components.{slot_name}: missing 'blend' path; skipping")
            return
        blend_abs = abspath_from_manifest(manifest_path, str(blend_rel))

        coll_name = merged.get("blend_collection") or merged.get("collection")
        if coll_name is None:
            warn(f"components.{slot_name}: missing 'blend_collection' (will fall back to first EXPORT_*)")

        link = bool(merged.get("link", True))

        fallback_names = []
        # Helpful fallbacks
        if isinstance(coll_name, str) and coll_name:
            # allow user to specify without EXPORT_ prefix
            if not coll_name.startswith("EXPORT_"):
                fallback_names.append("EXPORT_" + coll_name)
        fallback_names += ["Collection"]

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
        rot = merged.get("rotation_deg", [0.0, 0.0, 0.0])
        sc = merged.get("scale", 1.0)

        instance_collection(
            f"INST_{slot_name}",
            collection=coll,
            location_mm=loc,
            rotation_deg=rot,
            scale=sc,
            parent_obj=rig_root,
            target_collection=comp_subcol,
        )

    for side in ("left", "right"):
        side_block = comp_cfg.get(side, {}) if isinstance(comp_cfg.get(side, {}), dict) else {}
        for kind in ("electrical", "mechanical"):
            spec = side_block.get(kind, {}) if isinstance(side_block.get(kind, {}), dict) else {}
            if not spec:
                continue
            build_component(f"{side}_{kind}", spec)

    # ----------------
    # Preview camera (not included in export collection)
    # ----------------
    cam_cfg = cfg.get("preview_camera", {}) if isinstance(cfg.get("preview_camera", {}), dict) else {}
    if bool(cam_cfg.get("enabled", True)):
        cam_name = str(cam_cfg.get("name", "CAM_ElectroMechIso"))
        cam = ensure_camera(cam_name)

        # Put the camera into a separate collection so it is not part of export
        preview_col = ensure_collection("PREVIEW")
        move_object_to_collection(cam, preview_col)

        # Camera settings
        try:
            cam.data.lens = float(cam_cfg.get("lens_mm", 85.0))
        except Exception:
            pass
        try:
            cam.data.sensor_width = float(cam_cfg.get("sensor_width_mm", 36.0))
        except Exception:
            pass

        direction = cam_cfg.get("direction", [1.0, 1.0, 1.0])
        dvec = Vector([float(direction[0]), float(direction[1]), float(direction[2])])
        if dvec.length < 1e-9:
            dvec = Vector((1.0, 1.0, 1.0))

        distance_mm = float(cam_cfg.get("distance_mm", 1200.0))
        loc = dvec.normalized() * distance_mm
        cam.location = loc

        target_mm = cam_cfg.get("target_mm", [0.0, 0.0, 0.0])
        point_camera_at(cam, target_mm)

        # Optional: set as scene camera for quick viewport preview
        try:
            bpy.context.scene.camera = cam
        except Exception:
            pass

    # ----------------
    # Pack images (optional)
    # ----------------
    pack_images = bool(out_cfg.get("pack_images", False)) and (not no_pack_images)
    if pack_images:
        try:
            bpy.ops.file.pack_all()
            info("Packed external files (images)")
        except Exception as e:
            warn(f"Failed to pack external files: {e!r}")

    # Save
    compress = bool(out_cfg.get("compress", True))
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(out_abs), compress=compress)
    except TypeError:
        # Some Blender builds may not support compress arg
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

    # Units: 1 BU = 1 mm
    apply_units(cfg)

    # Build
    build_scene(cfg, manifest_path, output_override=args.output, no_pack_images=args.no_pack_images)


if __name__ == "__main__":
    main()
