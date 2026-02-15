"""poster/blendlib.py

Declarative, reproducible scene builder for the poster project.

Highlights:
- Units: 1 Blender Unit = 1 mm (scene.unit_settings.scale_length = 0.001)
- Perspective camera + "POSTER space" overlays (planes/text parented to camera)
- Import GLB/WRL assets reproducibly (clears ASSET_<name> collection then reimports)
- Preserves glTF import hierarchy (prevents parts shifting)
- Stores imported-asset root empties in HELPERS (reduces WORLD clutter)
- Blender 5 compatible transparency/material APIs
- Adds Cycles render settings support via manifest["cycles"]
- Respects per-object `"enabled": false` in the manifest
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from mathutils import Euler, Vector, Matrix


# ----------------------------
# Manifest + path helpers
# ----------------------------


def load_manifest(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def abspath_from_manifest(manifest_path: str | Path, maybe_rel: str | Path) -> str:
    """Resolve a path referenced by the manifest.

    1) Absolute paths are returned as-is.
    2) Relative paths are resolved against the directory containing the manifest.
    3) If that doesn't exist, we also try resolving against the repo root
       (parent of the manifest directory), so manifests can use "assets/..."
       while living under "poster/".
    """
    mp = Path(manifest_path).resolve()
    p = Path(maybe_rel)

    if p.is_absolute():
        return str(p)

    cand1 = (mp.parent / p).resolve()
    if cand1.exists():
        return str(cand1)

    cand2 = (mp.parent.parent / p).resolve()
    return str(cand2)


# ----------------------------
# Collection + object plumbing
# ----------------------------


def ensure_collection(name: str) -> bpy.types.Collection:
    scene = bpy.context.scene
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)

    if scene.collection.children.get(col.name) is None:
        try:
            scene.collection.children.link(col)
        except RuntimeError:
            pass
    return col


def ensure_child_collection(
    parent: bpy.types.Collection, name: str
) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if parent.children.get(col.name) is None:
        try:
            parent.children.link(col)
        except RuntimeError:
            pass
    return col


def move_object_to_collection(obj: bpy.types.Object, col: bpy.types.Collection) -> None:
    for c in list(obj.users_collection):
        try:
            c.objects.unlink(obj)
        except Exception:
            pass
    if col.objects.get(obj.name) is None:
        col.objects.link(obj)


def remove_collection_objects(col: bpy.types.Collection) -> None:
    for obj in list(col.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def remove_startup_objects(names: Sequence[str] = ("Cube", "Camera", "Light")) -> None:
    """Remove Blender's default startup objects by name."""
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj is None:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def ensure_empty(
    name: str, location_mm: Sequence[float] = (0.0, 0.0, 0.0)
) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = "PLAIN_AXES"
        bpy.context.scene.collection.objects.link(obj)
    obj.location = Vector(location_mm)
    return obj


def ensure_camera(name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        cam_data = bpy.data.cameras.new(name + "_DATA")
        obj = bpy.data.objects.new(name, cam_data)
        bpy.context.scene.collection.objects.link(obj)
    return obj


def set_world_transform(
    obj: bpy.types.Object,
    location_mm: Sequence[float],
    rotation_deg: Sequence[float],
    scale_xyz: Sequence[float],
) -> None:
    obj.location = Vector(location_mm)
    obj.rotation_euler = Euler([math.radians(v) for v in rotation_deg], "XYZ")
    obj.scale = Vector(scale_xyz)


# ----------------------------
# Mesh + materials
# ----------------------------


def _ensure_plane_uv(mesh: bpy.types.Mesh) -> None:
    """Ensure our generated 1x1 plane has UVs covering [0..1]^2."""
    if mesh.uv_layers:
        return
    uv_layer = mesh.uv_layers.new(name="UVMap")
    quad_uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for poly in mesh.polygons:
        if len(poly.loop_indices) != 4:
            continue
        for li, uv in zip(poly.loop_indices, quad_uvs):
            uv_layer.data[li].uv = uv


def ensure_plane_mesh(mesh_name: str) -> bpy.types.Mesh:
    """Deterministic 1x1 plane mesh on XY, centered at origin, with UVs."""
    mesh = bpy.data.meshes.get(mesh_name)
    if mesh is None:
        mesh = bpy.data.meshes.new(mesh_name)
        verts = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
    _ensure_plane_uv(mesh)
    return mesh


def ensure_material_principled(
    name: str,
    *,
    color_rgba: Sequence[float],
    roughness: float = 0.8,
    specular: float = 0.2,
    metallic: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        # Reset to default nodes
        for n in list(nodes):
            nodes.remove(n)
        out = nodes.new("ShaderNodeOutputMaterial")
        out.location = (350, 0)
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = (
        float(color_rgba[0]),
        float(color_rgba[1]),
        float(color_rgba[2]),
        float(color_rgba[3]),
    )
    bsdf.inputs["Roughness"].default_value = float(roughness)
    if "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = float(specular)
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    return mat


def _set_material_transparency(
    mat: bpy.types.Material, method: str = "BLENDED"
) -> None:
    """Set transparency behavior (Blender-version tolerant)."""
    m = method.upper()
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = m  # 'OPAQUE','DITHERED','BLENDED','CLIP'
        except Exception:
            pass
    elif hasattr(mat, "blend_method"):
        legacy = {"OPAQUE": "OPAQUE", "BLENDED": "BLEND", "CLIP": "CLIP"}.get(
            m, "BLEND"
        )
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
) -> bpy.types.Material:
    """Unlit image material (Emission), with alpha support (Transparent mix)."""
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
# Poster math + overlays
# ----------------------------


def poster_plane_distance_mm(
    poster_width_mm: float, lens_mm: float, sensor_width_mm: float
) -> float:
    """Distance from camera origin to the poster image plane.

    We use a perspective camera with sensor_fit='HORIZONTAL'. In that case, the
    camera frustum width at distance d is:

        width = d * sensor_width / lens

    so:

        d = width * lens / sensor_width

    For non-square posters, *poster_width_mm* is the horizontal poster dimension.
    """
    return float(poster_width_mm) * float(lens_mm) / float(sensor_width_mm)


def poster_dimensions_mm(cfg: Dict[str, Any]) -> Tuple[float, float, float]:
    """Return (width_mm, height_mm, safe_margin_mm) from cfg.

    Backwards compatible:
      - If cfg['poster'].width_mm/height_mm are present, use them.
      - Else fall back to cfg['poster'].size_mm (square poster).
    """
    poster = cfg.get("poster", {})
    safe_margin_mm = float(poster.get("safe_margin_mm", 25.4))

    if "width_mm" in poster or "height_mm" in poster:
        w = float(poster.get("width_mm", poster.get("size_mm", 1219.2)))
        h = float(poster.get("height_mm", poster.get("size_mm", 1219.2)))
    else:
        s = float(poster.get("size_mm", 1219.2))
        w, h = s, s

    return w, h, safe_margin_mm


def place_on_poster_plane(
    obj: bpy.types.Object,
    cam_obj: bpy.types.Object,
    plane_distance_mm: float,
    poster_xy_mm: Sequence[float],
    z_mm: float,
) -> None:
    obj.parent = cam_obj
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = Vector(
        (
            float(poster_xy_mm[0]),
            float(poster_xy_mm[1]),
            -plane_distance_mm + float(z_mm),
        )
    )
    obj.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")


def poster_ray_dir_cam(
    poster_xy_mm: Sequence[float], plane_distance_mm: float
) -> Vector:
    """Ray direction in *camera local space* through a poster-plane point.

    poster_xy_mm are in poster mm coordinates (0,0 is center) on the poster image plane.
    """
    v = Vector(
        (float(poster_xy_mm[0]), float(poster_xy_mm[1]), -float(plane_distance_mm))
    )
    if v.length <= 1e-9:
        return Vector((0.0, 0.0, -1.0))
    return v.normalized()


def place_on_poster_ray(
    obj: bpy.types.Object,
    cam_obj: bpy.types.Object,
    plane_distance_mm: float,
    poster_xy_mm: Sequence[float],
    *,
    distance_mm: float,
) -> None:
    """Parent obj to camera and place it along the view ray at a given camera distance."""
    obj.parent = cam_obj
    obj.matrix_parent_inverse = Matrix.Identity(4)
    d = float(distance_mm)
    if d < 1e-6:
        d = 1e-6
    obj.location = poster_ray_dir_cam(poster_xy_mm, plane_distance_mm) * d


def _quat_from_view_dir(
    desired_cam_dir_asset: Vector,
    desired_up_asset: Vector,
    actual_cam_dir_parent: Vector,
    *,
    parent_up: Vector = Vector((0.0, 1.0, 0.0)),
    roll_deg: float = 0.0,
) -> "mathutils.Quaternion":
    """Quaternion mapping asset-local vectors into parent space.

    We interpret desired_cam_dir_asset as the direction from the asset origin *to the camera*
    in asset-local coordinates.

    actual_cam_dir_parent is the direction from the asset origin *to the camera* in parent
    (camera-local if parent is camera) coordinates.

    The quaternion returned rotates asset-local space into parent space.
    """
    from mathutils import Quaternion  # local import (Blender)

    a = Vector(desired_cam_dir_asset)
    if a.length <= 1e-9:
        a = Vector((0.0, 0.0, 1.0))
    a.normalize()

    b = Vector(actual_cam_dir_parent)
    if b.length <= 1e-9:
        b = Vector((0.0, 0.0, 1.0))
    b.normalize()

    q = a.rotation_difference(b)

    # Roll alignment: rotate around b so that (q @ desired_up_asset) aligns to parent_up.
    up_a = Vector(desired_up_asset)
    if up_a.length <= 1e-9:
        up_a = Vector((0.0, 0.0, 1.0))
    up_a.normalize()

    up1 = q @ up_a
    if up1.length > 1e-9:
        up1.normalize()

    up2 = Vector(parent_up)
    if up2.length > 1e-9:
        up2.normalize()

    # Project onto plane perpendicular to b
    up1p = up1 - b * up1.dot(b)
    up2p = up2 - b * up2.dot(b)
    if up1p.length > 1e-6 and up2p.length > 1e-6:
        up1p.normalize()
        up2p.normalize()
        # Signed angle from up1p -> up2p about axis b
        cross = up1p.cross(up2p)
        ang = math.atan2(b.dot(cross), up1p.dot(up2p))
        q = Quaternion(b, ang) @ q

    if roll_deg:
        q = Quaternion(b, math.radians(float(roll_deg))) @ q

    return q


def _parse_target_vector(view_cfg: Any) -> Vector:
    """Parse a view 'target' / 'look_at' vector from an object's manifest 'view' block.

    Supported keys (aliases):
      - target_mm, target
      - look_at_mm, look_at
      - target_z_mm / look_at_z_mm / target_z / look_at_z (shorthand for [0,0,z])

    If view_cfg is not a dict or no target is provided, returns (0,0,0).
    """
    if not isinstance(view_cfg, dict):
        return Vector((0.0, 0.0, 0.0))

    tgt_val = view_cfg.get(
        "target_mm",
        view_cfg.get(
            "target", view_cfg.get("look_at_mm", view_cfg.get("look_at", None))
        ),
    )
    if tgt_val is not None:
        try:
            v = Vector(tgt_val)
            return v
        except Exception:
            pass

    tz = view_cfg.get(
        "target_z_mm",
        view_cfg.get(
            "look_at_z_mm", view_cfg.get("target_z", view_cfg.get("look_at_z", None))
        ),
    )
    if tz is not None:
        try:
            return Vector((0.0, 0.0, float(tz)))
        except Exception:
            return Vector((0.0, 0.0, 0.0))

    return Vector((0.0, 0.0, 0.0))


def _parse_view_config(
    view_cfg: Any,
) -> Tuple[Optional[Vector], Optional[Vector], float, Optional[float]]:
    """Parse an object's manifest 'view' block.

    We support two user-facing styles:

      1) Direction style (existing):
           view: {"dir":[dx,dy,dz], "up":[ux,uy,uz], "roll_deg":0}

         'dir' is the direction from the asset's origin *to the camera* in asset-local coords.
         The vector's magnitude is ignored for orientation (it is normalized internally).

      2) Virtual camera style (more intuitive):
           view: {
             "camera_pos_mm":[x,y,z],          # camera position in asset coords
             "target_mm":[0,0,0],             # what it looks at in asset coords (default: origin)
             "up":[0,0,1],                    # camera up reference in asset coords (default: Z+)
             "roll_deg": 0
           }

         or equivalently:

           view: {
             "camera_dir":[dx,dy,dz],          # direction from target -> camera in asset coords
             "camera_distance_mm": 500,        # optional; if present we can infer placement distance
             "target_mm":[0,0,0],
             "up":[0,0,1],
             "roll_deg": 0
           }

    Returns:
      (desired_cam_dir_asset, desired_up_asset, roll_deg, view_distance_mm)

    view_distance_mm is intended as a *default* placement distance (if the object did not
    specify its own distance_mm). It comes from:
      - |camera_pos_mm - target_mm| when camera_pos_mm is used, or
      - camera_distance_mm when camera_dir is used.
    """
    if not isinstance(view_cfg, dict):
        return (None, None, 0.0, None)

    roll_deg = float(view_cfg.get("roll_deg", 0.0))

    # Up vector (optional)
    up_val = view_cfg.get("up", view_cfg.get("up_mm", view_cfg.get("up_dir", None)))
    up_vec: Optional[Vector] = Vector(up_val) if up_val is not None else None

    # Look-at target (optional; default origin)
    tgt_vec = _parse_target_vector(view_cfg)

    # Camera position style
    cam_pos_val = view_cfg.get(
        "camera_pos_mm",
        view_cfg.get(
            "camera_pos",
            view_cfg.get(
                "cam_pos_mm", view_cfg.get("pos_mm", view_cfg.get("pos", None))
            ),
        ),
    )
    if cam_pos_val is not None:
        cam_pos = Vector(cam_pos_val)
        v = cam_pos - tgt_vec
        if v.length <= 1e-9:
            v = Vector((0.0, 0.0, 1.0))
            return (v, up_vec, roll_deg, None)
        return (v, up_vec, roll_deg, float(v.length))

    # Camera direction style (or legacy 'dir')
    dir_val = view_cfg.get(
        "camera_dir",
        view_cfg.get("cam_dir", view_cfg.get("dir", view_cfg.get("direction", None))),
    )
    dir_vec: Optional[Vector] = Vector(dir_val) if dir_val is not None else None

    dist_val = view_cfg.get(
        "camera_distance_mm",
        view_cfg.get(
            "camera_distance",
            view_cfg.get("distance_mm", view_cfg.get("distance", None)),
        ),
    )
    view_dist: Optional[float] = float(dist_val) if dist_val is not None else None

    return (dir_vec, up_vec, roll_deg, view_dist)


def _collection_object_origin(
    coll: bpy.types.Collection, obj_name: str
) -> Optional[Vector]:
    """Origin of a named object inside a loaded/linked collection, in collection-local coords."""
    try:
        for o in getattr(coll, "all_objects", []):
            if o.name == obj_name:
                return Vector(o.matrix_world.translation)
    except Exception:
        pass
    return None


def _collection_mesh_bounds_center(coll: bpy.types.Collection) -> Vector:
    """Center of the combined mesh bounds of a collection, in collection-local coords."""
    pts: List[Vector] = []
    try:
        for o in getattr(coll, "all_objects", []):
            if getattr(o, "type", "") != "MESH":
                continue
            mw = o.matrix_world
            for c in getattr(o, "bound_box", []):
                try:
                    pts.append(mw @ Vector(c))
                except Exception:
                    continue
    except Exception:
        pass

    if not pts:
        return Vector((0.0, 0.0, 0.0))

    min_v = Vector(
        (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
    )
    max_v = Vector(
        (max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
    )
    return (min_v + max_v) * 0.5


def _collection_mesh_depth_range_cam(
    coll: bpy.types.Collection,
    *,
    root_loc_cam: Vector,
    q_asset_to_cam: "mathutils.Quaternion",
    scale_xyz: Sequence[float],
) -> Optional[Tuple[float, float]]:
    """Approximate (min_depth_mm, max_depth_mm) in camera-local coords for an instanced collection.

    Depth is measured as +distance along the camera forward direction (i.e., -Z in camera local space).
    """
    sx, sy, sz = float(scale_xyz[0]), float(scale_xyz[1]), float(scale_xyz[2])
    min_d: Optional[float] = None
    max_d: Optional[float] = None
    try:
        for o in getattr(coll, "all_objects", []):
            if getattr(o, "type", "") != "MESH":
                continue
            mw = o.matrix_world
            for c in getattr(o, "bound_box", []):
                p = mw @ Vector(c)
                p_scaled = Vector((p.x * sx, p.y * sy, p.z * sz))
                p_cam = root_loc_cam + (q_asset_to_cam @ p_scaled)
                depth = -float(p_cam.z)
                if min_d is None or depth < min_d:
                    min_d = depth
                if max_d is None or depth > max_d:
                    max_d = depth
    except Exception:
        return None

    if min_d is None or max_d is None:
        return None
    return (float(min_d), float(max_d))


def _instancer_mesh_depth_range_cam_depsgraph(
    instancer_obj: bpy.types.Object,
    cam_obj: bpy.types.Object,
) -> Optional[Tuple[float, float]]:
    """Compute (min_depth_mm, max_depth_mm) in camera-local coords for a *collection instance*.

    This uses the evaluated depsgraph's object_instances, so it reflects the *actual* instanced
    transforms Blender will render (including parenting, constraints, and library-link quirks).

    Depth is measured as +distance along the camera forward direction (i.e., -Z in camera local space).
    """
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        cam_eval = cam_obj.evaluated_get(depsgraph)
        inv_cam = cam_eval.matrix_world.inverted()
    except Exception:
        return None

    min_d: Optional[float] = None
    max_d: Optional[float] = None

    try:
        for inst in getattr(depsgraph, "object_instances", []):
            inst_obj = getattr(inst, "instance_object", None)
            if inst_obj is None:
                continue

            # Compare against the original (non-evaluated) instancer object.
            try:
                if getattr(inst_obj, "original", inst_obj) != instancer_obj:
                    continue
            except Exception:
                if getattr(inst_obj, "name", "") != getattr(instancer_obj, "name", ""):
                    continue

            obj = getattr(inst, "object", None)
            if obj is None or getattr(obj, "type", "") != "MESH":
                continue

            mw = getattr(inst, "matrix_world", None)
            if mw is None:
                continue

            for c in getattr(obj, "bound_box", []):
                p_world = mw @ Vector(c)
                p_cam = inv_cam @ p_world
                depth = -float(p_cam.z)
                if min_d is None or depth < min_d:
                    min_d = depth
                if max_d is None or depth > max_d:
                    max_d = depth
    except Exception:
        return None

    if min_d is None or max_d is None:
        return None
    return (float(min_d), float(max_d))


# ----------------------------
# Scene setup
# ----------------------------


def apply_units(cfg: Dict[str, Any]) -> None:
    u = cfg.get("units", {})
    scene = bpy.context.scene
    scene.unit_settings.system = u.get("system", "METRIC")
    scene.unit_settings.length_unit = u.get("length_unit", "MILLIMETERS")
    scene.unit_settings.scale_length = float(
        u.get("scale_length", 0.001)
    )  # 1 BU = 1 mm


def apply_color_management(cfg: Dict[str, Any]) -> None:
    r = cfg.get("render", {})
    scene = bpy.context.scene

    vt = r.get("view_transform", None)
    if vt:
        try:
            scene.view_settings.view_transform = vt
        except Exception:
            for fallback in ("AgX", "Standard"):
                try:
                    scene.view_settings.view_transform = fallback
                    break
                except Exception:
                    pass

    look = r.get("look", None)
    if look:
        try:
            scene.view_settings.look = look
        except Exception:
            pass

    if "exposure" in r:
        try:
            scene.view_settings.exposure = float(r["exposure"])
        except Exception:
            pass
    if "gamma" in r:
        try:
            scene.view_settings.gamma = float(r["gamma"])
        except Exception:
            pass


def configure_cycles_devices(cfg: Dict[str, Any]) -> None:
    """Select Cycles compute backend and devices (GPU/CPU) from cfg["cycles"].

    Expected manifest keys (all optional):
      cycles.device: "GPU" | "CPU"                  (default: "GPU")
      cycles.compute_device_type: "HIP" | "CUDA" | "OPTIX" | "ONEAPI" | "METAL" | "NONE"
                                               (default: "HIP" on AMD)
      cycles.use_cpu: bool                           (default: false)
      cycles.use_all_gpus: bool                      (default: false)
      cycles.preferred_devices: ["name substr", ...] (default: [])
        - If provided, ONLY devices whose name contains any substring will be enabled.
        - When preferred_devices is non-empty, it overrides use_all_gpus.

    Notes:
    - We run renders with --factory-startup for reproducibility, so we set this every run.
    - If something fails, we gracefully fall back to CPU.
    """
    scene = bpy.context.scene
    if scene.render.engine != "CYCLES":
        return

    c = cfg.get("cycles", {})
    want_device = str(c.get("device", "GPU")).upper()
    compute = str(c.get("compute_device_type", "HIP")).upper()
    use_cpu = bool(c.get("use_cpu", False))
    use_all_gpus = bool(c.get("use_all_gpus", False))
    preferred_substrings = [
        str(s).strip() for s in (c.get("preferred_devices", []) or []) if str(s).strip()
    ]

    prefs = None
    try:
        addon = bpy.context.preferences.addons.get("cycles")
        if addon is None:
            try:
                bpy.ops.preferences.addon_enable(module="cycles")
            except Exception:
                pass
            addon = bpy.context.preferences.addons.get("cycles")
        if addon is not None:
            prefs = addon.preferences
    except Exception:
        prefs = None

    if prefs is None:
        # Can't configure prefs; at least set scene device
        try:
            scene.cycles.device = "GPU" if want_device == "GPU" else "CPU"
        except Exception:
            pass
        print(
            "[blendlib] WARN: Could not access Cycles preferences; device selection may not work."
        )
        return

    # Set compute backend (HIP for AMD)
    if hasattr(prefs, "compute_device_type"):
        try:
            prefs.compute_device_type = compute
        except Exception:
            for fallback in ("HIP", "CUDA", "OPTIX", "ONEAPI", "METAL", "NONE"):
                if fallback == compute:
                    continue
                try:
                    prefs.compute_device_type = fallback
                    compute = fallback
                    break
                except Exception:
                    continue

    # Refresh devices list
    try:
        prefs.get_devices()
    except Exception:
        try:
            prefs.refresh_devices()
        except Exception:
            pass

    enabled_gpus: List[str] = []
    enabled_cpu = False

    try:
        devices = list(getattr(prefs, "devices", []))
    except Exception:
        devices = []

    # Candidate GPUs for the selected compute backend (e.g. HIP)
    gpu_candidates = []
    for d in devices:
        try:
            dt = str(getattr(d, "type", "")).upper()
            if dt == compute:
                gpu_candidates.append(d)
        except Exception:
            pass

    # If user specified preferred_devices, it overrides use_all_gpus.
    if preferred_substrings:
        use_all_gpus = False

    # If using only one GPU and no preferred list was given, pick a "best" device.
    best_gpu = None
    if (
        want_device == "GPU"
        and (not preferred_substrings)
        and (not use_all_gpus)
        and gpu_candidates
    ):
        best_score = -(10**9)
        for d in gpu_candidates:
            name = str(getattr(d, "name", ""))
            up = name.upper()
            score = 0
            if "RADEON RX" in up:
                score += 100
            if " RX " in f" {up} " or "RX" in up:
                score += 60
            if "PRO" in up or " W" in f" {up} ":
                score += 25
            if "GRAPHICS" in up:
                score -= 40
            if "APU" in up or "INTEGRATED" in up:
                score -= 20
            if score > best_score:
                best_score = score
                best_gpu = d

    # Enable/disable devices
    try:
        for d in devices:
            dt = str(getattr(d, "type", "")).upper()
            name = str(getattr(d, "name", ""))

            if dt == "CPU":
                d.use = use_cpu
                enabled_cpu = enabled_cpu or bool(d.use)
                continue

            if want_device != "GPU" or dt != compute:
                d.use = False
                continue

            # dt == compute and want_device == GPU
            if preferred_substrings:
                d.use = any(sub.lower() in name.lower() for sub in preferred_substrings)
            else:
                if use_all_gpus:
                    d.use = True
                else:
                    d.use = (d == best_gpu) if best_gpu is not None else False

            if d.use:
                enabled_gpus.append(name)
    except Exception as e:
        print(f"[blendlib] WARN: Failed while enabling Cycles devices: {e!r}")

    # Tell Cycles to use GPU if we enabled at least one GPU, else CPU.
    try:
        if want_device == "GPU" and enabled_gpus:
            scene.cycles.device = "GPU"
        else:
            scene.cycles.device = "CPU"
    except Exception:
        pass

    try:
        cd = getattr(prefs, "compute_device_type", None)
        print(
            f"[blendlib] Cycles compute_device_type={cd} scene.cycles.device={getattr(scene.cycles,'device',None)}"
        )
    except Exception:
        pass
    if enabled_gpus:
        print(f"[blendlib] Enabled GPU devices: {enabled_gpus}")
    else:
        print(
            "[blendlib] WARN: No GPU devices enabled for Cycles; falling back to CPU."
        )
    if enabled_cpu:
        print("[blendlib] Enabled CPU device as well.")


def apply_cycles_settings(cfg: Dict[str, Any]) -> None:
    """Apply Cycles settings from cfg["cycles"] (safe across Blender versions)."""
    c = cfg.get("cycles", {})
    scene = bpy.context.scene
    if not hasattr(scene, "cycles"):
        return

    sc = scene.cycles

    def _set(attr: str, value: Any) -> None:
        if hasattr(sc, attr):
            try:
                setattr(sc, attr, value)
            except Exception:
                pass

    _set("samples", int(c.get("samples", 256)))
    _set("preview_samples", int(c.get("preview_samples", 64)))

    # Adaptive sampling
    if "use_adaptive_sampling" in c:
        _set("use_adaptive_sampling", bool(c["use_adaptive_sampling"]))
    if "adaptive_threshold" in c:
        _set("adaptive_threshold", float(c["adaptive_threshold"]))

    # Denoising (varies by version; try both scene and view-layer flags)
    if "use_denoising" in c:
        use_dn = bool(c["use_denoising"])
        _set("use_denoising", use_dn)
        try:
            bpy.context.view_layer.cycles.use_denoising = use_dn
        except Exception:
            pass

    if "denoiser" in c:
        den = str(c["denoiser"])
        _set("denoiser", den)
        try:
            bpy.context.view_layer.cycles.denoiser = den
        except Exception:
            pass

    # Light paths / bounces
    for k in (
        "max_bounces",
        "diffuse_bounces",
        "glossy_bounces",
        "transmission_bounces",
        "transparent_max_bounces",
        "volume_bounces",
        "filter_glossy",
        "clamp_indirect",
    ):
        if k in c:
            val = c[k]
            if isinstance(val, bool):
                _set(k, bool(val))
            elif isinstance(val, int):
                _set(k, int(val))
            else:
                _set(k, float(val))

    # Caustics toggle (names differ across versions; try a few)
    if "use_caustics" in c:
        v = bool(c["use_caustics"])
        for attr in ("caustics_reflective", "caustics_refractive", "use_caustics"):
            if hasattr(sc, attr):
                try:
                    setattr(sc, attr, v)
                except Exception:
                    pass


def apply_render_settings(
    cfg: Dict[str, Any],
    poster_width_in: float,
    poster_height_in: float,
    ppi_override: Optional[float] = None,
) -> None:
    scene = bpy.context.scene
    r = cfg.get("render", {})

    engine_pref = r.get(
        "engine_preference", ["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]
    )
    for eng in engine_pref:
        try:
            scene.render.engine = eng
            break
        except Exception:
            continue

    apply_color_management(cfg)

    scene.render.film_transparent = bool(r.get("film_transparent", False))
    scene.render.image_settings.file_format = r.get("file_format", "PNG")
    scene.render.image_settings.color_mode = r.get("color_mode", "RGBA")
    scene.render.image_settings.color_depth = str(r.get("color_depth", "16"))

    ppi = (
        float(ppi_override)
        if ppi_override is not None
        else float(cfg.get("poster", {}).get("ppi", 150))
    )
    res_x = int(round(float(poster_width_in) * ppi))
    res_y = int(round(float(poster_height_in) * ppi))
    scene.render.resolution_x = max(1, res_x)
    scene.render.resolution_y = max(1, res_y)
    scene.render.resolution_percentage = 100

    # If we are in Cycles, apply cycles settings
    if scene.render.engine == "CYCLES":
        configure_cycles_devices(cfg)
        apply_cycles_settings(cfg)


def apply_world_settings(cfg: Dict[str, Any]) -> None:
    wcfg = cfg.get("world", {})
    scene = bpy.context.scene

    if scene.world is None:
        scene.world = bpy.data.worlds.new("WORLD_Main")

    world = scene.world
    world.use_nodes = True

    # Deterministic simple world: Background -> World Output
    nt = world.node_tree
    nodes = nt.nodes
    links = nt.links
    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputWorld")
    out.location = (300, 0)

    bg = nodes.new("ShaderNodeBackground")
    bg.location = (0, 0)

    col = wcfg.get("background_color_rgba", [1.0, 1.0, 1.0, 1.0])
    strength = float(wcfg.get("strength", 1.0))
    bg.inputs["Color"].default_value = (
        float(col[0]),
        float(col[1]),
        float(col[2]),
        float(col[3]),
    )
    bg.inputs["Strength"].default_value = strength

    links.new(bg.outputs["Background"], out.inputs["Surface"])


def ensure_camera_and_guides(cfg: Dict[str, Any]) -> Tuple[bpy.types.Object, float]:
    scene = bpy.context.scene
    poster = cfg.get("poster", {})
    cam_cfg = cfg.get("camera", {})

    poster_w_mm, poster_h_mm, safe_margin_mm = poster_dimensions_mm(cfg)

    cam = ensure_camera(cam_cfg.get("name", "CAM_Poster"))
    cam.data.type = "PERSP"
    cam.data.lens = float(cam_cfg.get("lens_mm", 85.0))
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.sensor_width = float(cam_cfg.get("sensor_width_mm", 36.0))

    cam.location = Vector(cam_cfg.get("location_mm", [0.0, -1750.0, 750.0]))
    cam.data.clip_start = float(cam_cfg.get("clip_start_mm", 10.0))
    cam.data.clip_end = float(cam_cfg.get("clip_end_mm", 200000.0))

    target = ensure_empty("EMPTY_CamTarget", cam_cfg.get("target_mm", [0.0, 0.0, 0.0]))

    # Track-to constraint
    track = None
    for c in cam.constraints:
        if c.type == "TRACK_TO":
            track = c
            break
    if track is None:
        track = cam.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    scene.camera = cam

    d_mm = poster_plane_distance_mm(poster_w_mm, cam.data.lens, cam.data.sensor_width)

    helpers = ensure_collection("HELPERS")

    # Poster reference plane (wireframe, hidden in renders)
    plane = bpy.data.objects.get("REF_PosterImagePlane")
    if plane is None:
        mesh = ensure_plane_mesh("REF_PosterImagePlane_MESH")
        plane = bpy.data.objects.new("REF_PosterImagePlane", mesh)
        scene.collection.objects.link(plane)
    plane.display_type = "WIRE"
    plane.hide_render = True
    move_object_to_collection(plane, helpers)
    plane.parent = cam
    plane.matrix_parent_inverse = Matrix.Identity(4)
    plane.location = Vector((0.0, 0.0, -d_mm))
    plane.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    plane.scale = Vector((poster_w_mm, poster_h_mm, 1.0))

    # Safe area guide
    safe = bpy.data.objects.get("REF_SafeArea")
    if safe is None:
        mesh = ensure_plane_mesh("REF_SafeArea_MESH")
        safe = bpy.data.objects.new("REF_SafeArea", mesh)
        scene.collection.objects.link(safe)
    safe.display_type = "WIRE"
    safe.hide_render = True
    move_object_to_collection(safe, helpers)
    safe.parent = cam
    safe.matrix_parent_inverse = Matrix.Identity(4)
    safe.location = Vector((0.0, 0.0, -d_mm + 0.5))
    safe.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    safe_w = max(1.0, poster_w_mm - 2.0 * safe_margin_mm)
    safe_h = max(1.0, poster_h_mm - 2.0 * safe_margin_mm)
    safe.scale = Vector((safe_w, safe_h, 1.0))

    return cam, d_mm


# ----------------------------
# Lighting
# ----------------------------


def _ensure_track_to(
    obj: bpy.types.Object,
    target: bpy.types.Object,
    *,
    track_axis: str = "TRACK_NEGATIVE_Z",
    up_axis: str = "UP_Y",
) -> None:
    """Ensure a Track To constraint exists on obj pointing at target.

    track_axis examples:
      - 'TRACK_NEGATIVE_Z' (camera/lights default)
      - 'TRACK_POSITIVE_Z' (useful for planes whose +Z should face the target)

    up_axis examples:
      - 'UP_Y' (camera style: +Y is "up")
      - 'UP_Z'
    """
    c = None
    for cc in obj.constraints:
        if cc.type == "TRACK_TO":
            c = cc
            break
    if c is None:
        c = obj.constraints.new(type="TRACK_TO")
    c.target = target
    try:
        c.track_axis = str(track_axis)
    except Exception:
        c.track_axis = "TRACK_NEGATIVE_Z"
    try:
        c.up_axis = str(up_axis)
    except Exception:
        c.up_axis = "UP_Y"


def _ensure_area_light(
    name: str, cfg: Dict[str, Any], lights_col: bpy.types.Collection
) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        light_data = bpy.data.lights.new(name + "_DATA", type="AREA")
        obj = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(obj)

    move_object_to_collection(obj, lights_col)

    if "location_mm" in cfg:
        obj.location = Vector(cfg["location_mm"])

    if "rotation_deg" in cfg:
        obj.rotation_euler = Euler(
            [math.radians(v) for v in cfg["rotation_deg"]], "XYZ"
        )

    if "color_rgb" in cfg:
        try:
            obj.data.color = (
                float(cfg["color_rgb"][0]),
                float(cfg["color_rgb"][1]),
                float(cfg["color_rgb"][2]),
            )
        except Exception:
            pass

    energy = cfg.get("energy", cfg.get("power", None))
    if energy is not None:
        obj.data.energy = float(energy)

    if (
        "size_xy_mm" in cfg
        and isinstance(cfg["size_xy_mm"], (list, tuple))
        and len(cfg["size_xy_mm"]) == 2
    ):
        sx, sy = float(cfg["size_xy_mm"][0]), float(cfg["size_xy_mm"][1])
        try:
            obj.data.shape = "RECTANGLE"
            obj.data.size = sx
            obj.data.size_y = sy
        except Exception:
            obj.data.size = max(sx, sy)
    else:
        size = float(cfg.get("size_mm", 1000.0))
        obj.data.size = size

    if "target_mm" in cfg:
        tgt = ensure_empty(f"EMPTY_Target_{name}", cfg["target_mm"])
        _ensure_track_to(obj, tgt)

    return obj


def apply_light_rig(cfg: Dict[str, Any]) -> None:
    lights_cfg = cfg.get("lights", {})
    if not lights_cfg.get("enabled", True):
        return

    lights_col = ensure_collection("LIGHTS")

    rig = lights_cfg.get("rig", "three_area")
    if rig == "three_area":
        if lights_cfg.get("key", {}).get("enabled", True):
            _ensure_area_light("LIGHT_Key", lights_cfg.get("key", {}), lights_col)
        if lights_cfg.get("fill", {}).get("enabled", True):
            _ensure_area_light("LIGHT_Fill", lights_cfg.get("fill", {}), lights_col)
        if lights_cfg.get("rim", {}).get("enabled", True):
            _ensure_area_light("LIGHT_Rim", lights_cfg.get("rim", {}), lights_col)

    extras = lights_cfg.get("extras", [])
    if isinstance(extras, list):
        for lc in extras:
            if not isinstance(lc, dict):
                continue
            if not lc.get("enabled", True):
                continue
            lname = lc.get("name")
            if not lname:
                continue
            _ensure_area_light(lname, lc, lights_col)


# ----------------------------
# Studio backdrop (cyclorama)
# ----------------------------


def _make_cyclorama_mesh(
    mesh_name: str,
    *,
    width_mm: float,
    floor_depth_mm: float,
    wall_height_mm: float,
    radius_mm: float,
    segments: int = 16,
) -> bpy.types.Mesh:
    """Create/update a simple cyclorama mesh (floor + curved corner + wall)."""
    mesh = bpy.data.meshes.get(mesh_name)
    if mesh is None:
        mesh = bpy.data.meshes.new(mesh_name)

    seg = max(2, int(segments))

    # Cross-section points (y,z) in mm
    pts: List[Tuple[float, float]] = []
    pts.append((-float(floor_depth_mm), 0.0))
    pts.append((0.0, 0.0))

    r = float(radius_mm)
    for i in range(1, seg + 1):
        t = (math.pi * 0.5) * (i / seg)
        y = r * math.sin(t)
        z = r * (1.0 - math.cos(t))
        pts.append((y, z))

    pts.append((r, r + float(wall_height_mm)))

    half_w = float(width_mm) * 0.5

    verts: List[Tuple[float, float, float]] = []
    for y, z in pts:
        verts.append((-half_w, y, z))
        verts.append((half_w, y, z))

    faces: List[Tuple[int, int, int, int]] = []
    for j in range(len(pts) - 1):
        l0 = 2 * j
        r0 = 2 * j + 1
        l1 = 2 * (j + 1)
        r1 = 2 * (j + 1) + 1
        faces.append((l0, r0, r1, l1))

    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def ensure_backdrop(obj_cfg: Dict[str, Any]) -> bpy.types.Object:
    name = obj_cfg["name"]
    mesh_name = name + "_MESH"

    width_mm = float(obj_cfg.get("width_mm", 6000))
    floor_depth_mm = float(obj_cfg.get("floor_depth_mm", 4000))
    wall_height_mm = float(obj_cfg.get("wall_height_mm", 3000))
    radius_mm = float(obj_cfg.get("radius_mm", 600))
    segments = int(obj_cfg.get("segments", 24))

    mesh = _make_cyclorama_mesh(
        mesh_name,
        width_mm=width_mm,
        floor_depth_mm=floor_depth_mm,
        wall_height_mm=wall_height_mm,
        radius_mm=radius_mm,
        segments=segments,
    )

    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
    else:
        obj.data = mesh

    mat_cfg = obj_cfg.get("material", {})
    color = mat_cfg.get("color_rgba", [1.0, 1.0, 1.0, 1.0])
    rough = float(mat_cfg.get("roughness", 0.95))
    spec = float(mat_cfg.get("specular", 0.0))
    mat = ensure_material_principled(
        f"MAT_{name}", color_rgba=color, roughness=rough, specular=spec
    )
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    set_world_transform(
        obj,
        obj_cfg.get("location_mm", [0.0, 0.0, 0.0]),
        obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0]),
        obj_cfg.get("scale", [1.0, 1.0, 1.0]),
    )

    return obj


# ----------------------------
# Overlay objects
# ----------------------------


def _as_xy(v: Any, *, default: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return float(v[0]), float(v[1])
        except Exception:
            return default
    if isinstance(v, (int, float)):
        f = float(v)
        return f, f
    return default


def _parse_anchor(anchor: Any) -> Tuple[str, str]:
    """Parse an anchor specification into (h_anchor, v_anchor).

    Supported forms:
      - "TOP" | "BOTTOM" | "LEFT" | "RIGHT" | "CENTER"
      - ["LEFT"|"CENTER"|"RIGHT", "BOTTOM"|"CENTER"|"TOP"]
    """
    if isinstance(anchor, str):
        a = anchor.strip().upper()
        if a in {"TOP", "BOTTOM", "CENTER"}:
            return "CENTER", a
        if a in {"LEFT", "RIGHT"}:
            return a, "CENTER"
        return "CENTER", "CENTER"

    if isinstance(anchor, (list, tuple)) and len(anchor) >= 2:
        h = str(anchor[0]).strip().upper()
        v = str(anchor[1]).strip().upper()
        if h not in {"LEFT", "CENTER", "RIGHT"}:
            h = "CENTER"
        if v not in {"BOTTOM", "CENTER", "TOP"}:
            v = "CENTER"
        return h, v

    return "CENTER", "CENTER"


def _poster_xy_from_anchor(
    *,
    anchor: Any,
    size_mm: Tuple[float, float],
    poster_w_mm: float,
    poster_h_mm: float,
    margin_mm: Tuple[float, float] = (0.0, 0.0),
    offset_mm: Tuple[float, float] = (0.0, 0.0),
) -> Tuple[float, float]:
    """Compute poster_xy_mm for a rectangle centered inside the poster."""
    w_mm, h_mm = float(size_mm[0]), float(size_mm[1])
    half_w = float(poster_w_mm) * 0.5
    half_h = float(poster_h_mm) * 0.5
    mx, my = float(margin_mm[0]), float(margin_mm[1])
    ox, oy = float(offset_mm[0]), float(offset_mm[1])

    h_anchor, v_anchor = _parse_anchor(anchor)

    if h_anchor == "LEFT":
        x = -half_w + mx + (w_mm * 0.5)
    elif h_anchor == "RIGHT":
        x = half_w - mx - (w_mm * 0.5)
    else:
        x = 0.0

    if v_anchor == "BOTTOM":
        y = -half_h + my + (h_mm * 0.5)
    elif v_anchor == "TOP":
        y = half_h - my - (h_mm * 0.5)
    else:
        y = 0.0

    return x + ox, y + oy


def ensure_image_plane(
    obj_cfg: Dict[str, Any],
    manifest_path: str | Path,
    cam_obj: bpy.types.Object,
    poster_plane_distance: float,
    *,
    poster_w_mm: float,
    poster_h_mm: float,
    safe_margin_mm: float,
) -> bpy.types.Object:
    """Create/update an image plane.

    Two placement modes:

    1) space="POSTER"
       - The plane is parented to the camera and positioned in "poster mm" coordinates so that
         poster_xy_mm and size_mm correspond to millimeters in the rendered poster image.
       - Optional: screen_lock (default true) keeps the on-screen size/position constant even if
         you move the plane closer/farther via z_mm (uses similar triangles).

       Extra optional keys (POSTER):
         poster_xy_mm: [x_mm, y_mm] on the poster (0,0 is center)
         size_mm: [w_mm, h_mm] on the poster
         anchor: "TOP"|"BOTTOM"|"LEFT"|"RIGHT"|"CENTER" or [h,v]
         margin_mm: number or [mx,my] (used with anchor/fit); default uses safe_margin_mm
         offset_mm: [dx,dy] (used with anchor)
         fit_width: bool (if true, set width to poster_w_mm - 2*margin_x)
         fit_height: bool (if true, set height to poster_h_mm - 2*margin_y)
         maintain_aspect: bool (default true) when fit_width/fit_height compute the other dim
         height_mm: explicit height when fit_width is true (optional)
         width_mm: explicit width when fit_height is true (optional)
         z_mm: distance offset toward the camera (mm). Larger -> closer to camera.
         screen_lock: bool (default true) keep screen size/position constant when z_mm != 0.
         aim_target_mm: [x,y,z] world-space point the plane's normal line passes through
         aim_target_name: string name for the helper empty (optional)
         aim_track_axis: e.g. 'TRACK_NEGATIVE_Z' or 'TRACK_POSITIVE_Z' (default: TRACK_NEGATIVE_Z)
         aim_up_axis: e.g. 'UP_Y' (default: UP_Y)

    2) space="WORLD"
       - The plane is placed in world space with location_mm/rotation_deg and scaled by size_mm.
         The 'scale' vector (if present) multiplies size_mm.
    """
    name = obj_cfg["name"]
    obj = bpy.data.objects.get(name)
    if obj is None:
        mesh = ensure_plane_mesh(name + "_MESH")
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
    else:
        _ensure_plane_uv(obj.data)

    # Material
    img_path = abspath_from_manifest(manifest_path, obj_cfg["image_path"])
    # Also load image datablock now so we can optionally compute aspect ratio.
    img = None
    try:
        img = bpy.data.images.load(img_path, check_existing=True)
    except Exception:
        img = None
    strength = float(obj_cfg.get("emission_strength", 1.0))
    mat = ensure_material_image_emission(
        "MAT_" + name, img_path, emission_strength=strength
    )
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    # Overlay objects should not cast shadows
    try:
        obj.visible_shadow = False
    except Exception:
        pass

    # In Cycles, keep overlay planes from affecting lighting/reflections.
    try:
        obj.cycles_visibility.camera = True
        obj.cycles_visibility.diffuse = False
        obj.cycles_visibility.glossy = False
        obj.cycles_visibility.transmission = False
        obj.cycles_visibility.shadow = False
        obj.cycles_visibility.scatter = False
    except Exception:
        pass

    # Placement / sizing
    # 1) Explicit size_mm: [w,h]
    # 2) Or fit_width / fit_height (optional maintain_aspect using the source image)
    w_mm, h_mm = 100.0, 100.0
    if "size_mm" in obj_cfg:
        w0, h0 = obj_cfg.get("size_mm", [100.0, 100.0])
        w_mm, h_mm = float(w0), float(h0)
    else:
        margin_xy = _as_xy(
            obj_cfg.get("margin_mm", None), default=(safe_margin_mm, safe_margin_mm)
        )
        mx, my = float(margin_xy[0]), float(margin_xy[1])

        fit_w = bool(obj_cfg.get("fit_width", False)) or (
            str(obj_cfg.get("fit", "")).upper() == "WIDTH"
        )
        fit_h = bool(obj_cfg.get("fit_height", False)) or (
            str(obj_cfg.get("fit", "")).upper() == "HEIGHT"
        )
        keep_aspect = bool(obj_cfg.get("maintain_aspect", True))

        # Prefer fit_width if both are set.
        if fit_w:
            w_mm = float(obj_cfg.get("width_mm", (float(poster_w_mm) - 2.0 * mx)))
            if "height_mm" in obj_cfg:
                h_mm = float(obj_cfg.get("height_mm"))
            elif keep_aspect and img is not None and getattr(img, "size", None):
                try:
                    px_w = float(img.size[0])
                    px_h = float(img.size[1])
                    if px_w > 1e-6:
                        h_mm = w_mm * (px_h / px_w)
                except Exception:
                    pass
        elif fit_h:
            h_mm = float(obj_cfg.get("height_mm", (float(poster_h_mm) - 2.0 * my)))
            if "width_mm" in obj_cfg:
                w_mm = float(obj_cfg.get("width_mm"))
            elif keep_aspect and img is not None and getattr(img, "size", None):
                try:
                    px_w = float(img.size[0])
                    px_h = float(img.size[1])
                    if px_h > 1e-6:
                        w_mm = h_mm * (px_w / px_h)
                except Exception:
                    pass

    w_mm = float(w_mm)
    h_mm = float(h_mm)

    space = str(obj_cfg.get("space", "WORLD")).upper()
    if space == "POSTER":
        z_mm = float(obj_cfg.get("z_mm", 0.0))
        screen_lock = bool(obj_cfg.get("screen_lock", True))

        # Similar-triangles factor: moving closer changes physical size/offset,
        # but we want the same on-screen layout when screen_lock is True.
        f = 1.0
        if screen_lock:
            d_ref = float(poster_plane_distance)
            d_actual = d_ref - z_mm
            if d_actual <= 1e-6:
                d_actual = 1e-6
            f = d_actual / d_ref

        obj.scale = Vector((w_mm * f, h_mm * f, 1.0))

        # Poster position: explicit poster_xy_mm OR anchor-based placement.
        if "poster_xy_mm" in obj_cfg:
            poster_xy = obj_cfg.get("poster_xy_mm", [0.0, 0.0])
            base_px = float(poster_xy[0])
            base_py = float(poster_xy[1])
        elif "anchor" in obj_cfg:
            # If the user is anchoring and didn't specify margin_mm, default to safe margin.
            margin_xy = _as_xy(
                obj_cfg.get("margin_mm", None), default=(safe_margin_mm, safe_margin_mm)
            )
            offset_xy = _as_xy(obj_cfg.get("offset_mm", None), default=(0.0, 0.0))
            base_px, base_py = _poster_xy_from_anchor(
                anchor=obj_cfg.get("anchor"),
                size_mm=(w_mm, h_mm),
                poster_w_mm=poster_w_mm,
                poster_h_mm=poster_h_mm,
                margin_mm=margin_xy,
                offset_mm=offset_xy,
            )
        else:
            base_px, base_py = 0.0, 0.0

        # Store on-poster layout info for optional overlap checking/debug boxes.
        try:
            root["poster_layout_xy_mm"] = (float(base_px), float(base_py))
            if "layout_size_mm" in obj_cfg:
                ls = obj_cfg.get("layout_size_mm", [0.0, 0.0])
                if isinstance(ls, (list, tuple)) and len(ls) >= 2:
                    root["poster_layout_size_mm"] = (float(ls[0]), float(ls[1]))
        except Exception:
            pass

        # Store on-poster layout info for optional overlap checking/debug boxes.
        try:
            obj["poster_layout_xy_mm"] = (float(base_px), float(base_py))
            obj["poster_layout_size_mm"] = (float(w_mm), float(h_mm))
        except Exception:
            pass

        px = base_px * f if screen_lock else base_px
        py = base_py * f if screen_lock else base_py

        place_on_poster_plane(obj, cam_obj, poster_plane_distance, [px, py], z_mm)

        # Optional "aim" so a perpendicular ray through the plane center passes through a world point.
        aim_enabled = ("aim_target_mm" in obj_cfg) or ("aim_target_name" in obj_cfg)
        if aim_enabled:
            aim_loc = obj_cfg.get("aim_target_mm", [0.0, 0.0, 0.0])
            aim_name = obj_cfg.get("aim_target_name", f"EMPTY_AimTarget_{name}")
            tgt = ensure_empty(aim_name, aim_loc)
            try:
                tgt.hide_render = True
                tgt.hide_viewport = True
            except Exception:
                pass
            try:
                move_object_to_collection(tgt, ensure_collection("HELPERS"))
            except Exception:
                pass

            track_axis = str(obj_cfg.get("aim_track_axis", "TRACK_NEGATIVE_Z"))
            up_axis = str(obj_cfg.get("aim_up_axis", "UP_Y"))
            _ensure_track_to(obj, tgt, track_axis=track_axis, up_axis=up_axis)
        else:
            # Determinism: if the user removes aim_* keys, remove existing Track To constraints.
            try:
                for c in list(obj.constraints):
                    if c.type == "TRACK_TO":
                        obj.constraints.remove(c)
            except Exception:
                pass

    else:
        # WORLD space (unparent + place)
        try:
            obj.parent = None
        except Exception:
            pass
        try:
            for c in list(obj.constraints):
                if c.type == "TRACK_TO":
                    obj.constraints.remove(c)
        except Exception:
            pass

        loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])
        rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
        sc = obj_cfg.get("scale", [1.0, 1.0, 1.0])
        scale_xyz = [w_mm * float(sc[0]), h_mm * float(sc[1]), float(sc[2])]

        set_world_transform(obj, loc, rot, scale_xyz)

        # Clear poster layout custom props if present.
        try:
            if "poster_layout_xy_mm" in obj:
                del obj["poster_layout_xy_mm"]
            if "poster_layout_size_mm" in obj:
                del obj["poster_layout_size_mm"]
        except Exception:
            pass

    return obj


# ----------------------------
# Asset import (GLB / WRL)
# ----------------------------


def _import_objects_and_get_new(import_op) -> List[bpy.types.Object]:
    before = {o.as_pointer() for o in bpy.data.objects}
    import_op()
    return [o for o in bpy.data.objects if o.as_pointer() not in before]


def ensure_imported_asset(
    obj_cfg: Dict[str, Any], manifest_path: str | Path, importer: str
) -> bpy.types.Object:
    """Import a GLB/WRL and wrap it under a stable Empty root named obj_cfg['name'].

    Visible geometry lives in ASSET_<name> (child collection under obj_cfg['collection']).
    Root Empty is stored in HELPERS to reduce WORLD clutter.
    """
    name = obj_cfg["name"]
    parent_collection_name = obj_cfg.get("collection", "WORLD")
    parent_col = ensure_collection(parent_collection_name)
    asset_col = ensure_child_collection(parent_col, f"ASSET_{name}")
    helpers_col = ensure_collection("HELPERS")

    # Stable root empty
    root = bpy.data.objects.get(name)
    if root is None:
        root = bpy.data.objects.new(name, None)
        root.empty_display_type = "PLAIN_AXES"
        bpy.context.scene.collection.objects.link(root)
    root.hide_render = True
    move_object_to_collection(root, helpers_col)

    desired_loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])
    desired_rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
    desired_scale = obj_cfg.get("scale", [1.0, 1.0, 1.0])
    import_scale = float(obj_cfg.get("import_scale", 1.0))

    # Identity root during parenting
    root.parent = None
    root.location = Vector((0.0, 0.0, 0.0))
    root.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    root.scale = Vector((1.0, 1.0, 1.0))

    # Clear prior import
    remove_collection_objects(asset_col)

    filepath = abspath_from_manifest(manifest_path, obj_cfg["filepath"])
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Asset file not found: {filepath}")

    if importer == "glb":

        def op():
            bpy.ops.import_scene.gltf(filepath=filepath)

    elif importer == "wrl":

        def op():
            bpy.ops.import_scene.x3d(filepath=filepath)

    else:
        raise ValueError(f"Unknown importer: {importer}")

    new_objs = _import_objects_and_get_new(op)

    # Move imported objects into asset collection (preserve hierarchy)
    for o in new_objs:
        if o.type in {"CAMERA", "LIGHT"}:
            continue
        move_object_to_collection(o, asset_col)

    # Parent only top-level imported objects to root, preserving transforms
    new_ptrs = {o.as_pointer() for o in new_objs}
    top_level: List[bpy.types.Object] = []
    for o in new_objs:
        if o.type in {"CAMERA", "LIGHT"}:
            continue
        if o.parent is None:
            top_level.append(o)
        else:
            try:
                if o.parent.as_pointer() not in new_ptrs:
                    top_level.append(o)
            except Exception:
                top_level.append(o)

    for o in top_level:
        mw = o.matrix_world.copy()
        o.parent = root
        o.matrix_parent_inverse = root.matrix_world.inverted()
        o.matrix_world = mw

    # Apply final transform to root (include import_scale)
    combined_scale = Vector(desired_scale) * import_scale
    set_world_transform(root, desired_loc, desired_rot, combined_scale)
    return root


# ----------------------------
# 3D Text (optional)
# ----------------------------


def ensure_text_object(
    obj_cfg: Dict[str, Any],
    manifest_path: str | Path,
    styles: Dict[str, Any],
    cam_obj: bpy.types.Object,
    poster_plane_distance: float,
) -> bpy.types.Object:
    """Create/update a 3D text object (FONT curve)."""
    name = obj_cfg["name"]

    curve = bpy.data.curves.get(name + "_FONT")
    if curve is None:
        curve = bpy.data.curves.new(name + "_FONT", type="FONT")

    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, curve)
        bpy.context.scene.collection.objects.link(obj)
    else:
        obj.data = curve

    curve.body = obj_cfg.get("text", "")
    style_name = str(obj_cfg.get("style", ""))
    style = styles.get(style_name, {}) if isinstance(styles, dict) else {}

    curve.size = float(obj_cfg.get("size_mm", style.get("size_mm", 20.0)))
    curve.extrude = float(obj_cfg.get("extrude_mm", style.get("extrude_mm", 0.0)))

    if "align_x" in obj_cfg:
        try:
            curve.align_x = str(obj_cfg["align_x"])
        except Exception:
            pass
    if "align_y" in obj_cfg:
        try:
            curve.align_y = str(obj_cfg["align_y"])
        except Exception:
            pass

    font_rel = obj_cfg.get("font", style.get("font"))
    if font_rel:
        font_path = abspath_from_manifest(manifest_path, font_rel)
        if os.path.exists(font_path):
            try:
                curve.font = bpy.data.fonts.load(font_path, check_existing=True)
            except Exception:
                pass

    rgba = obj_cfg.get("color_rgba", style.get("color_rgba"))
    if rgba:
        rough = float(obj_cfg.get("roughness", style.get("roughness", 0.5)))
        spec = float(obj_cfg.get("specular", style.get("specular", 0.2)))
        metal = float(obj_cfg.get("metallic", style.get("metallic", 0.0)))
        mat = ensure_material_principled(
            "MAT_" + (style_name or name),
            color_rgba=rgba,
            roughness=rough,
            specular=spec,
            metallic=metal,
        )
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

    space = str(obj_cfg.get("space", "WORLD")).upper()
    if space == "POSTER":
        # Store optional layout info for overlap checking/debug boxes.
        try:
            obj["poster_layout_xy_mm"] = (
                float(obj_cfg.get("poster_xy_mm", [0.0, 0.0])[0]),
                float(obj_cfg.get("poster_xy_mm", [0.0, 0.0])[1]),
            )
            if "layout_size_mm" in obj_cfg:
                ls = obj_cfg.get("layout_size_mm", [0.0, 0.0])
                if isinstance(ls, (list, tuple)) and len(ls) >= 2:
                    obj["poster_layout_size_mm"] = (float(ls[0]), float(ls[1]))
        except Exception:
            pass
        place_on_poster_plane(
            obj,
            cam_obj,
            poster_plane_distance,
            obj_cfg.get("poster_xy_mm", [0.0, 0.0]),
            float(obj_cfg.get("z_mm", 0.0)),
        )
    else:
        # Clear poster layout props if present.
        try:
            if "poster_layout_xy_mm" in obj:
                del obj["poster_layout_xy_mm"]
            if "poster_layout_size_mm" in obj:
                del obj["poster_layout_size_mm"]
        except Exception:
            pass
        set_world_transform(
            obj,
            obj_cfg.get("location_mm", [0.0, 0.0, 0.0]),
            obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0]),
            obj_cfg.get("scale", [1.0, 1.0, 1.0]),
        )

    return obj


# ----------------------------
# Asset import (.blend library collections)
# ----------------------------


def _list_collections_in_blend(blend_path: str, *, link: bool = True) -> List[str]:
    blend_path = str(Path(blend_path).resolve())
    with bpy.data.libraries.load(blend_path, link=link) as (data_from, data_to):
        return list(getattr(data_from, "collections", []))


def _load_collection_from_blend(
    blend_path: str, collection_name: str, *, link: bool
) -> Optional[bpy.types.Collection]:
    blend_path = str(Path(blend_path).resolve())
    with bpy.data.libraries.load(blend_path, link=link) as (data_from, data_to):
        if collection_name not in getattr(data_from, "collections", []):
            return None
        data_to.collections = [collection_name]
    return data_to.collections[0]


def load_collection_from_blend(
    blend_path: str,
    *,
    collection_name: Optional[str] = None,
    fallback_names: Sequence[str] = (),
    link: bool = True,
) -> bpy.types.Collection:
    """Load a Collection datablock from an external .blend file, with robust fallbacks."""
    blend_path = str(Path(blend_path).resolve())
    available = _list_collections_in_blend(blend_path, link=link)
    if not available:
        raise RuntimeError(f"No collections found in blend library: {blend_path}")

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

    picked = None
    picked_name = None
    for cand in candidates:
        coll = _load_collection_from_blend(blend_path, cand, link=link)
        if coll is None:
            continue
        # Prefer non-empty
        try:
            n_objs = len(getattr(coll, "all_objects", []))
        except Exception:
            n_objs = 0
        if n_objs > 0:
            picked = coll
            picked_name = cand
            break
        if picked is None:
            picked = coll
            picked_name = cand

    if picked is None:
        raise RuntimeError(f"Failed to load any collection from {blend_path}")

    print(
        f"[blendlib] Loaded collection '{picked.name}' (picked='{picked_name}', requested='{collection_name}') from: {blend_path}"
    )
    return picked


def ensure_imported_blend_asset(
    obj_cfg: Dict[str, Any],
    manifest_path: str | Path,
    *,
    cam_obj: Optional[bpy.types.Object] = None,
    poster_plane_distance: Optional[float] = None,
    poster_w_mm: Optional[float] = None,
    poster_h_mm: Optional[float] = None,
    safe_margin_mm: float = 0.0,
) -> bpy.types.Object:
    """Instance a collection from an external .blend file into the scene.

    Supports both:
      - space="WORLD" (default): uses location_mm/rotation_deg/scale
      - space="POSTER": places the asset using poster coordinates relative to the poster camera.

    POSTER placement fields (recommended):
      poster_xy_mm: [x,y] on the poster (mm, origin at center)
      distance_mm: camera distance along the ray through (x,y) on the poster plane

      appearance_distance_mm (optional): if provided, the asset is uniformly scaled by
          (distance_mm / appearance_distance_mm) so its apparent size stays the same as if it
          were placed at appearance_distance_mm. This is useful for depth layering (front/back)
          without changing the rendered size.

    Alternative POSTER placement (legacy-style):
      z_mm + screen_lock (like image planes) place a single point near the poster plane.

    View/orientation (optional):

      Direction style (existing):
        view: {dir:[dx,dy,dz], up:[ux,uy,uz], roll_deg:0}
          - dir is the direction from the asset origin TO the camera in asset-local coords.
          - up defines the asset's "up" for roll alignment.

      Virtual camera style (more intuitive):
        view: {camera_pos_mm:[x,y,z], target_mm:[0,0,0], up:[0,0,1], roll_deg:0}
        or
        view: {camera_dir:[dx,dy,dz], camera_distance_mm:500, target_mm:[0,0,0], up:[0,0,1], roll_deg:0}

        If obj_cfg.distance_mm is omitted, camera_distance_mm (or |camera_pos_mm-target_mm|) is
        used as the default placement distance along the poster ray.

      rotation_deg: extra local rotation applied AFTER view alignment (still supported).
    """
    name = obj_cfg["name"]
    parent_col_name = obj_cfg.get("collection", "WORLD")

    parent_col = ensure_collection(parent_col_name)
    asset_col = ensure_child_collection(parent_col, f"ASSET_{name}")

    # Clear previous instancers/objects in the ASSET collection
    remove_collection_objects(asset_col)

    # Root transform handle (kept with the asset so hiding HELPERS doesn't hide the asset)
    root = ensure_empty(name, [0.0, 0.0, 0.0])
    # Empties do not render; avoid disabling render (can hide children in some setups).
    try:
        root.hide_render = False
    except Exception:
        pass
    move_object_to_collection(root, asset_col)

    blend_path = abspath_from_manifest(
        manifest_path, obj_cfg.get("filepath", obj_cfg.get("path", ""))
    )
    if not os.path.exists(blend_path):
        raise FileNotFoundError(f"Blend asset file not found: {blend_path}")
    requested = obj_cfg.get("blend_collection", None)
    link = bool(obj_cfg.get("link", True))

    requested_name: Optional[str] = str(requested) if requested is not None else None
    collection_for_instance: Optional[str] = requested_name

    requested_name: Optional[str] = str(requested) if requested is not None else None
    collection_for_instance: Optional[str] = requested_name

    # Collection selection policy:
    #
    # - By default, we instance exactly what the manifest requested (e.g. EXPORT_* if specified).
    # - If you set prefer_src: true (and don't force instance_export_wrapper), then requesting
    #   EXPORT_foo will instance SRC_foo instead (sometimes useful for "just the meshes").
    # - If you request an EXPORT_* wrapper but it contains no meshes, we fall back to SRC_* automatically
    #   (unless you set instance_export_wrapper: true).
    prefer_src = bool(obj_cfg.get("prefer_src", False))
    force_export = bool(obj_cfg.get("instance_export_wrapper", False))

    src_fallback_name: Optional[str] = None
    if requested_name and requested_name.startswith("EXPORT_"):
        suffix = requested_name[len("EXPORT_") :]
        src_fallback_name = f"SRC_{suffix}"
        if prefer_src and (not force_export):
            collection_for_instance = src_fallback_name

    # Fallback order: try a "SRC_<asset>" first (geometry), then EXPORT_<asset>, then
    # a same-named collection, then the generic default "Collection".
    fallback = [f"SRC_{name}", f"EXPORT_{name}", name, "Collection"]

    # If the user explicitly requested an EXPORT_* wrapper, keep it (and its RIG_* peer)
    # in the fallbacks, in case SRC_* doesn't exist in that library for some reason.
    if requested_name and requested_name.startswith("EXPORT_"):
        suffix = requested_name[len("EXPORT_") :]
        fallback = [requested_name, f"RIG_{suffix}"] + fallback

    coll = load_collection_from_blend(
        blend_path,
        collection_name=collection_for_instance,
        fallback_names=fallback,
        link=link,
    )

    # Log when the user asked for an EXPORT_* view but we intentionally instance SRC_* instead.
    if (
        requested_name
        and requested_name.startswith("EXPORT_")
        and collection_for_instance != requested_name
    ):
        print(
            f"[blendlib] Note: prefer_src enabled; requested '{requested_name}', instancing '{coll.name}' instead."
        )

    # If the manifest requested an EXPORT_* wrapper but it contains no meshes, fall back to SRC_* automatically
    # (unless the user forced the wrapper via instance_export_wrapper: true).
    if (
        requested_name
        and requested_name.startswith("EXPORT_")
        and (collection_for_instance == requested_name)
        and (not force_export)
        and src_fallback_name
    ):
        try:
            _all_tmp = getattr(coll, "all_objects", [])
            _mesh_tmp = sum(1 for o in _all_tmp if getattr(o, "type", "") == "MESH")
        except Exception:
            _mesh_tmp = 0

        if _mesh_tmp == 0:
            try:
                alt = _load_collection_from_blend(
                    blend_path, src_fallback_name, link=link
                )
            except Exception:
                alt = None
            if alt is not None:
                print(
                    f"[blendlib] Note: '{requested_name}' contains no meshes; instancing '{alt.name}' instead."
                )
                coll = alt

    # Helpful diagnostics when debugging missing imports:
    # - direct: objects directly in the chosen collection (EXPORT_* usually has 0)
    # - children: immediate child collections
    # - all: recursive object count
    # - mesh: recursive mesh count (should be >0 for visible geometry)
    try:
        _all = getattr(coll, "all_objects", [])
        n_all = len(_all)
        n_mesh = sum(1 for o in _all if getattr(o, "type", "") == "MESH")
        n_child = len(getattr(coll, "children", []))
        n_direct = len(getattr(coll, "objects", []))
        print(
            f"[blendlib] Collection stats for '{coll.name}': direct={n_direct} children={n_child} all={n_all} mesh={n_mesh}"
        )
    except Exception:
        pass

    inst_name = f"INST_{name}"
    old_inst = bpy.data.objects.get(inst_name)
    if old_inst is not None:
        try:
            bpy.data.objects.remove(old_inst, do_unlink=True)
        except Exception:
            pass

    inst = bpy.data.objects.new(inst_name, None)
    bpy.context.scene.collection.objects.link(inst)
    move_object_to_collection(inst, asset_col)

    inst.empty_display_type = "PLAIN_AXES"
    inst.instance_type = "COLLECTION"
    inst.instance_collection = coll

    inst.parent = root
    try:
        inst.matrix_parent_inverse = root.matrix_world.inverted()
    except Exception:
        pass

    sc = obj_cfg.get("scale", [1.0, 1.0, 1.0])
    import_scale = float(obj_cfg.get("import_scale", 1.0))
    sc2 = [
        float(sc[0]) * import_scale,
        float(sc[1]) * import_scale,
        float(sc[2]) * import_scale,
    ]

    space = str(obj_cfg.get("space", "WORLD")).upper()
    if space == "POSTER":
        if cam_obj is None or poster_plane_distance is None:
            raise ValueError(
                "import_blend with space='POSTER' requires cam_obj and poster_plane_distance"
            )

        # Parent the root to the poster camera so poster coordinates remain stable.
        root.parent = cam_obj
        root.matrix_parent_inverse = Matrix.Identity(4)

        # Placement target on poster
        if "poster_xy_mm" in obj_cfg:
            poster_xy = obj_cfg.get("poster_xy_mm", [0.0, 0.0])
            base_px, base_py = float(poster_xy[0]), float(poster_xy[1])
        elif (
            "anchor" in obj_cfg
            and (poster_w_mm is not None)
            and (poster_h_mm is not None)
        ):
            # Anchor requires a notion of object size; use layout_size_mm if provided.
            layout_sz = obj_cfg.get("layout_size_mm", None)
            if isinstance(layout_sz, (list, tuple)) and len(layout_sz) >= 2:
                w_l, h_l = float(layout_sz[0]), float(layout_sz[1])
            else:
                w_l, h_l = 0.0, 0.0
            margin_xy = _as_xy(
                obj_cfg.get("margin_mm", None), default=(safe_margin_mm, safe_margin_mm)
            )
            offset_xy = _as_xy(obj_cfg.get("offset_mm", None), default=(0.0, 0.0))
            base_px, base_py = _poster_xy_from_anchor(
                anchor=obj_cfg.get("anchor"),
                size_mm=(w_l, h_l),
                poster_w_mm=float(poster_w_mm),
                poster_h_mm=float(poster_h_mm),
                margin_mm=margin_xy,
                offset_mm=offset_xy,
            )
        else:
            base_px, base_py = 0.0, 0.0

        # Parse view (supports "virtual camera" style) so we can optionally infer distance.
        view_cfg = obj_cfg.get("view", None)
        parsed_view_dir, parsed_view_up, parsed_roll_deg, parsed_view_distance = (
            _parse_view_config(view_cfg)
        )

        # The point in asset-local coordinates the virtual camera is looking at.
        # We treat this as the *anchor point* that gets placed at poster_xy_mm (so if you
        # set target to [0,0,100], that point — not the asset origin — is what lands on the poster ray).
        target_asset = _parse_target_vector(view_cfg)

        # Optional auto-target selection for assets whose geometry is not centered at (0,0,0).
        # This affects BOTH:
        #   - where the asset is anchored on the poster (poster_xy_mm), and
        #   - the direction used for view alignment (the target is the point the virtual camera looks at).
        #
        # Usage:
        #   view: { "target_mode": "BOUNDS_CENTER", ... }
        #   view: { "target_object_name": "RIG_SOMETHING_ROOT", ... }
        if isinstance(view_cfg, dict):
            mode = str(view_cfg.get("target_mode", "")).upper()
            if mode in ("BOUNDS_CENTER", "MESH_BOUNDS_CENTER", "MESH_CENTER"):
                target_asset = _collection_mesh_bounds_center(coll)
            else:
                tname = view_cfg.get(
                    "target_object_name", view_cfg.get("target_object", None)
                )
                if tname:
                    vv = _collection_object_origin(coll, str(tname))
                    if vv is not None:
                        target_asset = vv

        # Choose placement distance:
        #   - explicit obj_cfg.distance_mm wins
        #   - otherwise we fall back to the view camera distance if provided
        dist_mm = None
        if "distance_mm" in obj_cfg:
            dist_mm = float(obj_cfg.get("distance_mm", float(poster_plane_distance)))
        elif parsed_view_distance is not None:
            dist_mm = float(parsed_view_distance)

        # Optional apparent-size lock: keep the asset's angular size constant while changing distance.
        # If appearance_distance_mm is provided, we scale the asset by (dist_mm / appearance_distance_mm).
        sc2_eff = sc2
        if dist_mm is not None and "appearance_distance_mm" in obj_cfg:
            ref_d = float(obj_cfg.get("appearance_distance_mm", float(dist_mm)))
            if ref_d <= 1e-6:
                ref_d = 1e-6
            k = float(dist_mm) / ref_d
            sc2_eff = [float(sc2[0]) * k, float(sc2[1]) * k, float(sc2[2]) * k]
        try:
            root["appearance_distance_mm"] = float(
                obj_cfg.get(
                    "appearance_distance_mm",
                    float(dist_mm) if dist_mm is not None else 0.0,
                )
            )
        except Exception:
            pass

        # Desired location (in *camera local space*) for the TARGET point on the poster ray/plane.
        if dist_mm is not None:
            L_target = poster_ray_dir_cam(
                [base_px, base_py], float(poster_plane_distance)
            ) * float(dist_mm)
        else:
            # Legacy-style: z_mm offset from poster plane, optionally screen_locked.
            z_mm = float(obj_cfg.get("z_mm", 0.0))
            screen_lock = bool(obj_cfg.get("screen_lock", True))

            f = 1.0
            if screen_lock:
                d_ref = float(poster_plane_distance)
                d_actual = d_ref - z_mm
                if d_actual <= 1e-6:
                    d_actual = 1e-6
                f = d_actual / d_ref

            L_target = Vector(
                (base_px * f, base_py * f, -float(poster_plane_distance) + z_mm)
            )

        # Store on-poster layout info for optional overlap checking/debug boxes.
        try:
            root["poster_layout_xy_mm"] = (float(base_px), float(base_py))
            if "layout_size_mm" in obj_cfg:
                ls = obj_cfg.get("layout_size_mm", [0.0, 0.0])
                if isinstance(ls, (list, tuple)) and len(ls) >= 2:
                    root["poster_layout_size_mm"] = (float(ls[0]), float(ls[1]))
        except Exception:
            pass

        # Orientation (virtual-camera view)
        view_dir = parsed_view_dir
        view_up = parsed_view_up
        view_roll = float(parsed_roll_deg)

        if view_dir is None:
            # Back-compat: allow top-level keys for view vectors
            view_dir = obj_cfg.get("view_dir", None)
        if view_up is None:
            view_up = obj_cfg.get("view_up", None)

        rot_deg = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])

        # We compute a quaternion for anchoring even if we ultimately set Euler rotation.
        q_final = Euler((0.0, 0.0, 0.0), "XYZ").to_quaternion()

        if view_dir is not None:
            desired_cam_dir_asset = Vector(view_dir)
            desired_up_asset = (
                Vector(view_up) if view_up is not None else Vector((0.0, 0.0, 1.0))
            )

            # Direction from the TARGET point to the camera in camera-local space
            actual_cam_dir_parent = -L_target
            if actual_cam_dir_parent.length <= 1e-9:
                actual_cam_dir_parent = Vector((0.0, 0.0, 1.0))

            q_view = _quat_from_view_dir(
                desired_cam_dir_asset,
                desired_up_asset,
                actual_cam_dir_parent,
                parent_up=Vector((0.0, 1.0, 0.0)),
                roll_deg=view_roll,
            )

            # Optional extra local rotation (still supported, but try to prefer view.roll_deg)
            q_off = Euler([math.radians(v) for v in rot_deg], "XYZ").to_quaternion()
            q_final = q_view @ q_off

            try:
                root.rotation_mode = "QUATERNION"
                root.rotation_quaternion = q_final
            except Exception:
                root.rotation_euler = q_final.to_euler("XYZ")
        else:
            # No view: interpret rotation_deg as a camera-relative rotation.
            try:
                root.rotation_mode = "XYZ"
            except Exception:
                pass
            e = Euler([math.radians(v) for v in rot_deg], "XYZ")
            root.rotation_euler = e
            q_final = e.to_quaternion()

        # Anchor translation: place the asset so that TARGET point lands at L_target.
        # Must account for root scale (local point is scaled then rotated then translated).
        target_scaled = Vector(
            (
                target_asset.x * sc2_eff[0],
                target_asset.y * sc2_eff[1],
                target_asset.z * sc2_eff[2],
            )
        )
        root.location = L_target - (q_final @ target_scaled)
        # Scale
        root.scale = Vector(sc2_eff)

        # Optional depth diagnostics to debug unexpected front/back ordering.
        if bool(obj_cfg.get("debug_depth", False)):
            try:
                # Anchor point in camera-local space (should equal L_target)
                anchor_cam = root.location + (q_final @ target_scaled)
                anchor_depth = -float(anchor_cam.z)
                dr = _instancer_mesh_depth_range_cam_depsgraph(inst, cam_obj)
                if dr is None:
                    dr = _collection_mesh_depth_range_cam(
                        coll,
                        root_loc_cam=Vector(root.location),
                        q_asset_to_cam=q_final,
                        scale_xyz=sc2_eff,
                    )
                if dr is None:
                    print(
                        f"[depth] {name}: anchor_depth={anchor_depth:.1f}mm (no mesh bounds available)"
                    )
                else:
                    dmin, dmax = dr
                    print(
                        f"[depth] {name}: anchor_depth={anchor_depth:.1f}mm, bbox_depth_range=[{dmin:.1f} .. {dmax:.1f}]mm"
                    )
            except Exception as e:
                print(f"[depth] {name}: (failed) {e}")

    else:
        # WORLD space placement (default)
        try:
            root.parent = None
        except Exception:
            pass

        # Clear poster layout custom props if present.
        try:
            if "poster_layout_xy_mm" in root:
                del root["poster_layout_xy_mm"]
            if "poster_layout_size_mm" in root:
                del root["poster_layout_size_mm"]
        except Exception:
            pass

        loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])
        rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
        set_world_transform(root, loc, rot, sc2)

    return root


# ----------------------------
# Poster layout diagnostics (optional)
# ----------------------------


def _iter_layout_boxes_from_scene() -> List[Tuple[str, float, float, float, float]]:
    """Collect (name, cx, cy, w, h) for objects that expose poster_layout_* custom props."""
    out: List[Tuple[str, float, float, float, float]] = []
    for obj in bpy.data.objects:
        if ("poster_layout_xy_mm" not in obj) or ("poster_layout_size_mm" not in obj):
            continue
        try:
            cx, cy = obj["poster_layout_xy_mm"]
            w, h = obj["poster_layout_size_mm"]
            cx, cy = float(cx), float(cy)
            w, h = float(w), float(h)
        except Exception:
            continue
        if w <= 0.0 or h <= 0.0:
            continue
        out.append((obj.name, cx, cy, w, h))
    return out


def _rect_from_center(
    cx: float, cy: float, w: float, h: float, *, pad: float = 0.0
) -> Tuple[float, float, float, float]:
    p = float(pad)
    hw = float(w) * 0.5 + p
    hh = float(h) * 0.5 + p
    return (cx - hw, cx + hw, cy - hh, cy + hh)  # x0,x1,y0,y1


def _overlap_area(
    r1: Tuple[float, float, float, float], r2: Tuple[float, float, float, float]
) -> float:
    x0 = max(r1[0], r2[0])
    x1 = min(r1[1], r2[1])
    y0 = max(r1[2], r2[2])
    y1 = min(r1[3], r2[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(x1 - x0) * float(y1 - y0)


def _remove_objects_by_prefix(prefix: str) -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(prefix):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass


def _ensure_layout_box_plane(
    name: str,
    *,
    cam_obj: bpy.types.Object,
    poster_plane_distance: float,
    center_xy_mm: Tuple[float, float],
    size_mm: Tuple[float, float],
    z_mm: float = 0.25,
) -> bpy.types.Object:
    """Create a non-rendering wireframe plane showing a reserved layout box."""
    obj_name = f"LAYOUTBOX_{name}"
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        mesh = ensure_plane_mesh(obj_name + "_MESH")
        obj = bpy.data.objects.new(obj_name, mesh)
        bpy.context.scene.collection.objects.link(obj)

    obj.display_type = "WIRE"
    obj.hide_render = True
    try:
        obj.show_in_front = True
    except Exception:
        pass

    w, h = float(size_mm[0]), float(size_mm[1])
    obj.scale = Vector((w, h, 1.0))

    place_on_poster_plane(
        obj,
        cam_obj,
        float(poster_plane_distance),
        [float(center_xy_mm[0]), float(center_xy_mm[1])],
        float(z_mm),
    )
    try:
        move_object_to_collection(obj, ensure_collection("HELPERS"))
    except Exception:
        pass
    return obj


def run_layout_diagnostics(
    *,
    cfg: Dict[str, Any],
    cam_obj: bpy.types.Object,
    poster_plane_distance: float,
    poster_w_mm: float,
    poster_h_mm: float,
    safe_margin_mm: float,
) -> None:
    """Optional overlap checks + debug box visualization."""
    layout = cfg.get("layout", {})
    if not isinstance(layout, dict):
        return

    check = bool(layout.get("check_overlaps", False))
    debug = bool(layout.get("debug_boxes", False))
    if not (check or debug):
        return

    pad = float(layout.get("padding_mm", 0.0))
    boxes = _iter_layout_boxes_from_scene()

    if check:
        # Safe area in poster coords
        half_w = float(poster_w_mm) * 0.5
        half_h = float(poster_h_mm) * 0.5
        safe_w = max(1.0, float(poster_w_mm) - 2.0 * float(safe_margin_mm))
        safe_h = max(1.0, float(poster_h_mm) - 2.0 * float(safe_margin_mm))
        safe = _rect_from_center(0.0, 0.0, safe_w, safe_h, pad=0.0)

        for n, cx, cy, w, h in boxes:
            r = _rect_from_center(cx, cy, w, h, pad=pad)
            # Outside full poster
            if r[0] < -half_w or r[1] > half_w or r[2] < -half_h or r[3] > half_h:
                print(f"[layout] WARN: '{n}' extends outside poster bounds")
            # Outside safe area
            if r[0] < safe[0] or r[1] > safe[1] or r[2] < safe[2] or r[3] > safe[3]:
                print(
                    f"[layout] WARN: '{n}' extends outside safe area (margin={safe_margin_mm}mm)"
                )

        # Pairwise overlap checks
        for i in range(len(boxes)):
            n1, x1, y1, w1, h1 = boxes[i]
            r1 = _rect_from_center(x1, y1, w1, h1, pad=pad)
            for j in range(i + 1, len(boxes)):
                n2, x2, y2, w2, h2 = boxes[j]
                r2 = _rect_from_center(x2, y2, w2, h2, pad=pad)
                area = _overlap_area(r1, r2)
                if area > 0.0:
                    print(
                        f"[layout] WARN: overlap '{n1}' vs '{n2}' (area≈{area:.1f} mm^2, pad={pad}mm)"
                    )

    if debug:
        _remove_objects_by_prefix("LAYOUTBOX_")
        for n, cx, cy, w, h in boxes:
            _ensure_layout_box_plane(
                n,
                cam_obj=cam_obj,
                poster_plane_distance=float(poster_plane_distance),
                center_xy_mm=(float(cx), float(cy)),
                size_mm=(float(w), float(h)),
                z_mm=float(layout.get("z_mm", 0.25)),
            )


# ----------------------------
# Main entrypoint
# ----------------------------


def apply_manifest(
    manifest_path: str | Path, *, ppi_override: Optional[float] = None
) -> Dict[str, Any]:
    cfg = load_manifest(manifest_path)

    if bool(cfg.get("scene", {}).get("remove_startup_objects", True)):
        remove_startup_objects()

    ensure_collection("WORLD")
    ensure_collection("OVERLAY")
    ensure_collection("HELPERS")
    ensure_collection("LIGHTS")

    apply_units(cfg)
    apply_world_settings(cfg)

    poster_w_mm, poster_h_mm, _safe_margin_mm = poster_dimensions_mm(cfg)
    apply_render_settings(
        cfg,
        poster_width_in=(poster_w_mm / 25.4),
        poster_height_in=(poster_h_mm / 25.4),
        ppi_override=ppi_override,
    )

    cam, plane_d_mm = ensure_camera_and_guides(cfg)
    apply_light_rig(cfg)

    # Build objects
    for obj_cfg in cfg.get("objects", []):
        if not obj_cfg.get("enabled", True):
            continue

        kind = obj_cfg.get("kind")
        collection_name = obj_cfg.get("collection", "WORLD")
        col = ensure_collection(collection_name)

        if kind == "text":
            styles = cfg.get("styles", {})
            obj = ensure_text_object(obj_cfg, manifest_path, styles, cam, plane_d_mm)
            move_object_to_collection(obj, col)

        elif kind == "image_plane":
            obj = ensure_image_plane(
                obj_cfg,
                manifest_path,
                cam,
                plane_d_mm,
                poster_w_mm=poster_w_mm,
                poster_h_mm=poster_h_mm,
                safe_margin_mm=_safe_margin_mm,
            )
            move_object_to_collection(obj, col)

        elif kind == "backdrop":
            obj = ensure_backdrop(obj_cfg)
            move_object_to_collection(obj, col)

        elif kind == "import_glb":
            ensure_imported_asset(obj_cfg, manifest_path, importer="glb")

        elif kind == "import_wrl":
            ensure_imported_asset(obj_cfg, manifest_path, importer="wrl")

        elif kind in ("import_blend", "instance_blend_collection"):
            ensure_imported_blend_asset(
                obj_cfg,
                manifest_path,
                cam_obj=cam,
                poster_plane_distance=plane_d_mm,
                poster_w_mm=poster_w_mm,
                poster_h_mm=poster_h_mm,
                safe_margin_mm=_safe_margin_mm,
            )

        else:
            print(f"[WARN] Unknown kind '{kind}' for object '{obj_cfg.get('name')}'")

    # Optional layout overlap checking + debug boxes
    try:
        run_layout_diagnostics(
            cfg=cfg,
            cam_obj=cam,
            poster_plane_distance=plane_d_mm,
            poster_w_mm=poster_w_mm,
            poster_h_mm=poster_h_mm,
            safe_margin_mm=_safe_margin_mm,
        )
    except Exception as e:
        print(f"[layout] Diagnostics error: {e}")

    return cfg
