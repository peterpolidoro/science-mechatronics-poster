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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from mathutils import Euler, Vector


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


def ensure_child_collection(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
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


def remove_collection_objects(col: bpy.types.Collection, keep: Optional[Sequence[str]] = None) -> None:
    """Remove all objects directly in a collection, optionally keeping some by name."""
    keep_set = set(keep or [])
    for obj in list(col.objects):
        if obj.name in keep_set:
            continue
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


def ensure_empty(name: str, location_mm: Sequence[float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = 'PLAIN_AXES'
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
    obj.rotation_euler = Euler([math.radians(v) for v in rotation_deg], 'XYZ')
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
        float(color_rgba[0]), float(color_rgba[1]), float(color_rgba[2]), float(color_rgba[3])
    )
    bsdf.inputs["Roughness"].default_value = float(roughness)
    if "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = float(specular)
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    return mat


def _set_material_transparency(mat: bpy.types.Material, method: str = "BLENDED") -> None:
    """Set transparency behavior (Blender-version tolerant)."""
    m = method.upper()
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
        img.alpha_mode = 'STRAIGHT'
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

def get_poster_dims_mm(cfg: Dict[str, Any]) -> Tuple[float, float, float]:
    """Return (width_mm, height_mm, safe_margin_mm).

    Supports legacy square posters via poster.size_mm.
    """
    poster = cfg.get("poster", {}) or {}
    if ("width_mm" in poster) or ("height_mm" in poster):
        w_mm = float(poster.get("width_mm", poster.get("size_mm", 1219.2)))
        h_mm = float(poster.get("height_mm", poster.get("size_mm", 1219.2)))
    else:
        s_mm = float(poster.get("size_mm", 1219.2))
        w_mm = s_mm
        h_mm = s_mm

    safe_margin_mm = float(poster.get("safe_margin_mm", 25.4))
    return w_mm, h_mm, safe_margin_mm


def poster_plane_distance_mm(poster_width_mm: float, lens_mm: float, sensor_width_mm: float) -> float:
    """Distance from camera to poster reference plane (mm).

    With camera.sensor_fit='HORIZONTAL', this chooses the distance such that a plane of width
    poster_width_mm exactly fills the render horizontally.
    """
    return poster_width_mm * lens_mm / sensor_width_mm


def poster_xy_to_world(
    cam_obj: bpy.types.Object,
    plane_distance_mm: float,
    poster_xy_mm: Sequence[float],
    distance_mm: float,
) -> Vector:
    """Convert a poster-plane coordinate to a world-space point along the camera ray.

    poster_xy_mm is specified on the poster plane in mm (0,0 is center).
    distance_mm is the desired distance from the camera to the point (mm).
    """
    v = Vector((float(poster_xy_mm[0]), float(poster_xy_mm[1]), -float(plane_distance_mm)))
    if v.length < 1e-9:
        direction = Vector((0.0, 0.0, -1.0))
    else:
        direction = v.normalized()

    local_point = direction * float(distance_mm)
    return cam_obj.matrix_world @ local_point
def place_on_poster_plane(
    obj: bpy.types.Object,
    cam_obj: bpy.types.Object,
    plane_distance_mm: float,
    poster_xy_mm: Sequence[float],
    z_mm: float,
) -> None:
    obj.parent = cam_obj
    obj.matrix_parent_inverse = cam_obj.matrix_world.inverted()
    obj.location = Vector((float(poster_xy_mm[0]), float(poster_xy_mm[1]), -plane_distance_mm + float(z_mm)))
    obj.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')


# ----------------------------
# Scene setup
# ----------------------------

def apply_units(cfg: Dict[str, Any]) -> None:
    u = cfg.get("units", {})
    scene = bpy.context.scene
    scene.unit_settings.system = u.get("system", "METRIC")
    scene.unit_settings.length_unit = u.get("length_unit", "MILLIMETERS")
    scene.unit_settings.scale_length = float(u.get("scale_length", 0.001))  # 1 BU = 1 mm


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
    if scene.render.engine != 'CYCLES':
        return

    c = cfg.get("cycles", {})
    want_device = str(c.get("device", "GPU")).upper()
    compute = str(c.get("compute_device_type", "HIP")).upper()
    use_cpu = bool(c.get("use_cpu", False))
    use_all_gpus = bool(c.get("use_all_gpus", False))
    preferred_substrings = [str(s).strip() for s in (c.get("preferred_devices", []) or []) if str(s).strip()]

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
            scene.cycles.device = 'GPU' if want_device == "GPU" else 'CPU'
        except Exception:
            pass
        print("[blendlib] WARN: Could not access Cycles preferences; device selection may not work.")
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
    if want_device == "GPU" and (not preferred_substrings) and (not use_all_gpus) and gpu_candidates:
        best_score = -10**9
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
            scene.cycles.device = 'GPU'
        else:
            scene.cycles.device = 'CPU'
    except Exception:
        pass

    try:
        cd = getattr(prefs, "compute_device_type", None)
        print(f"[blendlib] Cycles compute_device_type={cd} scene.cycles.device={getattr(scene.cycles,'device',None)}")
    except Exception:
        pass
    if enabled_gpus:
        print(f"[blendlib] Enabled GPU devices: {enabled_gpus}")
    else:
        print("[blendlib] WARN: No GPU devices enabled for Cycles; falling back to CPU.")
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

    engine_pref = r.get("engine_preference", ["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"])
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

    ppi = float(ppi_override) if ppi_override is not None else float(cfg.get("poster", {}).get("ppi", 150))
    scene.render.resolution_x = int(round(poster_width_in * ppi))
    scene.render.resolution_y = int(round(poster_height_in * ppi))
    scene.render.resolution_percentage = 100

    # If we are in Cycles, apply cycles settings
    if scene.render.engine == 'CYCLES':
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
    bg.inputs["Color"].default_value = (float(col[0]), float(col[1]), float(col[2]), float(col[3]))
    bg.inputs["Strength"].default_value = strength

    links.new(bg.outputs["Background"], out.inputs["Surface"])


def ensure_camera_and_guides(
    cfg: Dict[str, Any],
    *,
    poster_width_mm: float,
    poster_height_mm: float,
    safe_margin_mm: float,
) -> Tuple[bpy.types.Object, float]:
    scene = bpy.context.scene
    cam_cfg = cfg.get("camera", {})

    cam = ensure_camera(cam_cfg.get("name", "CAM_Poster"))
    cam.data.type = 'PERSP'
    cam.data.lens = float(cam_cfg.get("lens_mm", 85.0))
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.sensor_width = float(cam_cfg.get("sensor_width_mm", 36.0))

    cam.location = Vector(cam_cfg.get("location_mm", [0.0, -1750.0, 750.0]))
    cam.data.clip_start = float(cam_cfg.get("clip_start_mm", 10.0))
    cam.data.clip_end = float(cam_cfg.get("clip_end_mm", 200000.0))

    target = ensure_empty("EMPTY_CamTarget", cam_cfg.get("target_mm", [0.0, 0.0, 0.0]))

    # Track-to constraint
    track = None
    for c in cam.constraints:
        if c.type == 'TRACK_TO':
            track = c
            break
    if track is None:
        track = cam.constraints.new(type='TRACK_TO')
    track.target = target
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    scene.camera = cam

    # Plane distance is derived from POSTER WIDTH (horizontal sensor fit).
    d_mm = poster_plane_distance_mm(float(poster_width_mm), cam.data.lens, cam.data.sensor_width)

    helpers = ensure_collection("HELPERS")

    # Poster reference plane (wireframe, hidden in renders)
    plane = bpy.data.objects.get("REF_PosterImagePlane")
    if plane is None:
        mesh = ensure_plane_mesh("REF_PosterImagePlane_MESH")
        plane = bpy.data.objects.new("REF_PosterImagePlane", mesh)
        scene.collection.objects.link(plane)
    plane.display_type = 'WIRE'
    plane.hide_render = True
    move_object_to_collection(plane, helpers)
    plane.parent = cam
    plane.matrix_parent_inverse = cam.matrix_world.inverted()
    plane.location = Vector((0.0, 0.0, -d_mm))
    plane.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')
    plane.scale = Vector((float(poster_width_mm), float(poster_height_mm), 1.0))

    # Safe area guide (wireframe, hidden in renders)
    safe = bpy.data.objects.get("REF_SafeArea")
    if safe is None:
        mesh = ensure_plane_mesh("REF_SafeArea_MESH")
        safe = bpy.data.objects.new("REF_SafeArea", mesh)
        scene.collection.objects.link(safe)
    safe.display_type = 'WIRE'
    safe.hide_render = True
    move_object_to_collection(safe, helpers)
    safe.parent = cam
    safe.matrix_parent_inverse = cam.matrix_world.inverted()
    safe.location = Vector((0.0, 0.0, -d_mm + 0.5))
    safe.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')

    safe_w = max(1.0, float(poster_width_mm) - 2.0 * float(safe_margin_mm))
    safe_h = max(1.0, float(poster_height_mm) - 2.0 * float(safe_margin_mm))
    safe.scale = Vector((safe_w, safe_h, 1.0))

    return cam, d_mm
def _ensure_track_to(
    obj: bpy.types.Object,
    target: bpy.types.Object,
    *,
    track_axis: str = 'TRACK_NEGATIVE_Z',
    up_axis: str = 'UP_Y',
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
        if cc.type == 'TRACK_TO':
            c = cc
            break
    if c is None:
        c = obj.constraints.new(type='TRACK_TO')
    c.target = target
    try:
        c.track_axis = str(track_axis)
    except Exception:
        c.track_axis = 'TRACK_NEGATIVE_Z'
    try:
        c.up_axis = str(up_axis)
    except Exception:
        c.up_axis = 'UP_Y'


def _ensure_area_light(name: str, cfg: Dict[str, Any], lights_col: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        light_data = bpy.data.lights.new(name + "_DATA", type='AREA')
        obj = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(obj)

    move_object_to_collection(obj, lights_col)

    if "location_mm" in cfg:
        obj.location = Vector(cfg["location_mm"])

    if "rotation_deg" in cfg:
        obj.rotation_euler = Euler([math.radians(v) for v in cfg["rotation_deg"]], 'XYZ')

    if "color_rgb" in cfg:
        try:
            obj.data.color = (float(cfg["color_rgb"][0]), float(cfg["color_rgb"][1]), float(cfg["color_rgb"][2]))
        except Exception:
            pass

    energy = cfg.get("energy", cfg.get("power", None))
    if energy is not None:
        obj.data.energy = float(energy)

    if "size_xy_mm" in cfg and isinstance(cfg["size_xy_mm"], (list, tuple)) and len(cfg["size_xy_mm"]) == 2:
        sx, sy = float(cfg["size_xy_mm"][0]), float(cfg["size_xy_mm"][1])
        try:
            obj.data.shape = 'RECTANGLE'
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
            _ensure_area_light("LIGHT_Key",  lights_cfg.get("key", {}),  lights_col)
        if lights_cfg.get("fill", {}).get("enabled", True):
            _ensure_area_light("LIGHT_Fill", lights_cfg.get("fill", {}), lights_col)
        if lights_cfg.get("rim", {}).get("enabled", True):
            _ensure_area_light("LIGHT_Rim",  lights_cfg.get("rim", {}),  lights_col)

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
    for (y, z) in pts:
        verts.append((-half_w, y, z))
        verts.append(( half_w, y, z))

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
    mat = ensure_material_principled(f"MAT_{name}", color_rgba=color, roughness=rough, specular=spec)
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

def ensure_image_plane(
    obj_cfg: Dict[str, Any],
    manifest_path: str | Path,
    cam_obj: bpy.types.Object,
    poster_plane_distance: float,
    *,
    poster_width_mm: float,
    poster_height_mm: float,
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
         size_mm: [w_mm, h_mm] on the poster (base size; can be overridden by fit_* below)
         z_mm: distance offset toward the camera (mm). Larger -> closer to camera.
         screen_lock: bool (default true) keep screen size/position constant when z_mm != 0.

         fit_width: bool (default false)  -> fit width within margins
         fit_height: bool (default false) -> fit height within margins
         keep_aspect: bool (default true) -> keep aspect ratio when fitting
         margin_mm: number or [mx,my]     -> margins for fit/anchor (defaults to poster safe margin)

         anchor: [H,V] where H in {LEFT,CENTER,RIGHT} and V in {BOTTOM,CENTER,TOP}
                 If poster_xy_mm is omitted, anchor decides the position within margins.

         offset_mm: [dx,dy] additional offset after anchor calc (defaults to [0,0])

         (legacy / optional)
         aim_target_mm / aim_target_name / aim_track_axis / aim_up_axis:
           If present, add a Track To constraint to aim the plane at a target point.

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
    strength = float(obj_cfg.get("emission_strength", 1.0))
    mat = ensure_material_image_emission("MAT_" + name, img_path, emission_strength=strength)
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

    def _coerce_margin(val: Any, default_xy: Tuple[float, float]) -> Tuple[float, float]:
        if val is None:
            return default_xy
        if isinstance(val, (int, float)):
            v = float(val)
            return (v, v)
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            return (float(val[0]), float(val[1]))
        return default_xy

    def _parse_anchor(val: Any) -> Tuple[str, str]:
        if not val:
            return ("CENTER", "CENTER")
        if isinstance(val, str):
            # e.g. "TOP_RIGHT" or "RIGHT_TOP"
            parts = [p for p in re.split(r"[^A-Za-z]+", val.upper()) if p]
            h = "CENTER"
            v = "CENTER"
            for p in parts:
                if p in ("LEFT", "CENTER", "RIGHT"):
                    h = p
                if p in ("BOTTOM", "CENTER", "TOP"):
                    v = p
            return (h, v)
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            return (str(val[0]).upper(), str(val[1]).upper())
        return ("CENTER", "CENTER")

    # Base size
    w_mm, h_mm = obj_cfg.get("size_mm", [100.0, 100.0])
    w0 = float(w_mm)
    h0 = float(h_mm)
    w_mm = w0
    h_mm = h0

    # Fit sizing / anchoring only applies in POSTER mode
    space = str(obj_cfg.get("space", "WORLD")).upper()
    if space == "POSTER":
        mx, my = _coerce_margin(obj_cfg.get("margin_mm", None), (float(safe_margin_mm), float(safe_margin_mm)))
        fit_w = bool(obj_cfg.get("fit_width", False))
        fit_h = bool(obj_cfg.get("fit_height", False))
        keep_aspect = bool(obj_cfg.get("keep_aspect", True))

        if fit_w or fit_h:
            target_w = max(1.0, float(poster_width_mm) - 2.0 * mx)
            target_h = max(1.0, float(poster_height_mm) - 2.0 * my)

            if keep_aspect and (w0 > 1e-6) and (h0 > 1e-6):
                sx = target_w / w0 if fit_w else 1.0e9
                sy = target_h / h0 if fit_h else 1.0e9
                s = min(sx, sy)
                if s == 1.0e9:
                    s = 1.0
                w_mm = w0 * s
                h_mm = h0 * s
            else:
                if fit_w:
                    w_mm = target_w
                if fit_h:
                    h_mm = target_h

        # Position: poster_xy_mm takes precedence; otherwise compute from anchor.
        if "poster_xy_mm" in obj_cfg:
            poster_xy = obj_cfg.get("poster_xy_mm", [0.0, 0.0])
            px = float(poster_xy[0])
            py = float(poster_xy[1])
        else:
            h_anchor, v_anchor = _parse_anchor(obj_cfg.get("anchor", None))
            if h_anchor == "LEFT":
                px = -float(poster_width_mm) * 0.5 + mx + w_mm * 0.5
            elif h_anchor == "RIGHT":
                px = float(poster_width_mm) * 0.5 - mx - w_mm * 0.5
            else:
                px = 0.0

            if v_anchor == "BOTTOM":
                py = -float(poster_height_mm) * 0.5 + my + h_mm * 0.5
            elif v_anchor == "TOP":
                py = float(poster_height_mm) * 0.5 - my - h_mm * 0.5
            else:
                py = 0.0

        off = obj_cfg.get("offset_mm", [0.0, 0.0])
        try:
            px += float(off[0])
            py += float(off[1])
        except Exception:
            pass

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

        px2 = px * f if screen_lock else px
        py2 = py * f if screen_lock else py
        place_on_poster_plane(obj, cam_obj, poster_plane_distance, [px2, py2], z_mm)

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
                    if c.type == 'TRACK_TO':
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
                if c.type == 'TRACK_TO':
                    obj.constraints.remove(c)
        except Exception:
            pass

        loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])
        rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
        sc = obj_cfg.get("scale", [1.0, 1.0, 1.0])
        scale_xyz = [w_mm * float(sc[0]), h_mm * float(sc[1]), float(sc[2])]

        set_world_transform(obj, loc, rot, scale_xyz)

    return obj
def _import_objects_and_get_new(import_op) -> List[bpy.types.Object]:
    before = {o.as_pointer() for o in bpy.data.objects}
    import_op()
    return [o for o in bpy.data.objects if o.as_pointer() not in before]


def ensure_imported_asset(obj_cfg: Dict[str, Any], manifest_path: str | Path, importer: str) -> bpy.types.Object:
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
        root.empty_display_type = 'PLAIN_AXES'
        bpy.context.scene.collection.objects.link(root)
    # NOTE: Empties don't render, but hiding the root can hide children/instances in some setups.
    try:
        root.hide_render = bool(obj_cfg.get("hide_root", False))
    except Exception:
        pass
    move_object_to_collection(root, asset_col)

    desired_loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])
    desired_rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
    desired_scale = obj_cfg.get("scale", [1.0, 1.0, 1.0])
    import_scale = float(obj_cfg.get("import_scale", 1.0))

    # Identity root during parenting
    root.parent = None
    root.location = Vector((0.0, 0.0, 0.0))
    root.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')
    root.scale = Vector((1.0, 1.0, 1.0))

    # Clear prior import
    remove_collection_objects(asset_col, keep=[root.name])

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
    combined_scale = (Vector(desired_scale) * import_scale)
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
        curve = bpy.data.curves.new(name + "_FONT", type='FONT')

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
        mat = ensure_material_principled("MAT_" + (style_name or name), color_rgba=rgba, roughness=rough, specular=spec, metallic=metal)
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

    space = str(obj_cfg.get("space", "WORLD")).upper()
    if space == "POSTER":
        place_on_poster_plane(
            obj,
            cam_obj,
            poster_plane_distance,
            obj_cfg.get("poster_xy_mm", [0.0, 0.0]),
            float(obj_cfg.get("z_mm", 0.0)),
        )
    else:
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


def _load_collection_from_blend(blend_path: str, collection_name: str, *, link: bool) -> Optional[bpy.types.Collection]:
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

    print(f"[blendlib] Loaded collection '{picked.name}' (picked='{picked_name}', requested='{collection_name}') from: {blend_path}")
    return picked


def ensure_imported_blend_asset(
    obj_cfg: Dict[str, Any],
    manifest_path: str | Path,
    *,
    cam_obj: Optional[bpy.types.Object] = None,
    poster_plane_distance: Optional[float] = None,
) -> bpy.types.Object:
    """Instance a collection from an external .blend file into the scene.

    Supports two placement modes:

    - space="WORLD" (default): uses location_mm / rotation_deg / scale
    - space="POSTER": uses poster_xy_mm + distance_mm along the camera ray
    """
    name = obj_cfg["name"]
    parent_col_name = obj_cfg.get("collection", "WORLD")

    parent_col = ensure_collection(parent_col_name)
    helpers_col = ensure_collection("HELPERS")
    asset_col = ensure_child_collection(parent_col, f"ASSET_{name}")

    # Root transform handle (kept in HELPERS)
    root = ensure_empty(name, [0.0, 0.0, 0.0])
    # Empties don't render, but hide_render can affect children/instances in some setups.
    try:
        root.hide_render = bool(obj_cfg.get("hide_root", False))
    except Exception:
        pass
    move_object_to_collection(root, asset_col)

    # Clear previous instancers/objects in the ASSET collection
    remove_collection_objects(asset_col, keep=[root.name])

    blend_path = abspath_from_manifest(manifest_path, obj_cfg.get("filepath", obj_cfg.get("path", "")))
    if not os.path.exists(blend_path):
        raise FileNotFoundError(f"Blend asset file not found: {blend_path}")

    requested = obj_cfg.get("blend_collection", None)
    link = bool(obj_cfg.get("link", True))
    fallback = [f"EXPORT_{name}", name, "Collection"]

    coll = load_collection_from_blend(
        blend_path,
        collection_name=str(requested) if requested is not None else None,
        fallback_names=fallback,
        link=link,
    )

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

    inst.empty_display_type = 'PLAIN_AXES'
    inst.instance_type = 'COLLECTION'
    inst.instance_collection = coll

    # IMPORTANT: instancer empties must NOT be hidden in render, or instances disappear.
    try:
        inst.hide_render = False
    except Exception:
        pass

    inst.parent = root
    try:
        inst.matrix_parent_inverse = root.matrix_world.inverted()
    except Exception:
        pass

    # Placement
    space = str(obj_cfg.get("space", "WORLD")).upper()
    if space == "POSTER":
        if cam_obj is None or poster_plane_distance is None:
            raise RuntimeError(f"Blend asset '{name}' requested space=POSTER but cam_obj/poster_plane_distance were not provided.")
        poster_xy = obj_cfg.get("poster_xy_mm", [0.0, 0.0])
        distance_mm = float(obj_cfg.get("distance_mm", obj_cfg.get("camera_distance_mm", float(poster_plane_distance))))
        loc_v = poster_xy_to_world(cam_obj, float(poster_plane_distance), poster_xy, distance_mm)
        loc = [float(loc_v.x), float(loc_v.y), float(loc_v.z)]
    else:
        loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])

    rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
    sc = obj_cfg.get("scale", [1.0, 1.0, 1.0])
    import_scale = float(obj_cfg.get("import_scale", 1.0))
    sc2 = [float(sc[0]) * import_scale, float(sc[1]) * import_scale, float(sc[2]) * import_scale]

    set_world_transform(root, loc, rot, sc2)
    return root
def apply_manifest(manifest_path: str | Path, *, ppi_override: Optional[float] = None) -> Dict[str, Any]:
    cfg = load_manifest(manifest_path)

    if bool(cfg.get("scene", {}).get("remove_startup_objects", True)):
        remove_startup_objects()

    ensure_collection("WORLD")
    ensure_collection("OVERLAY")
    ensure_collection("HELPERS")
    ensure_collection("LIGHTS")

    apply_units(cfg)
    apply_world_settings(cfg)

    poster_w_mm, poster_h_mm, safe_margin_mm = get_poster_dims_mm(cfg)

    poster_w_in = poster_w_mm / 25.4
    poster_h_in = poster_h_mm / 25.4
    apply_render_settings(cfg, poster_w_in, poster_h_in, ppi_override=ppi_override)

    cam, plane_d_mm = ensure_camera_and_guides(
        cfg,
        poster_width_mm=poster_w_mm,
        poster_height_mm=poster_h_mm,
        safe_margin_mm=safe_margin_mm,
    )
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
                poster_width_mm=poster_w_mm,
                poster_height_mm=poster_h_mm,
                safe_margin_mm=safe_margin_mm,
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
            )

        else:
            print(f"[WARN] Unknown kind '{kind}' for object '{obj_cfg.get('name')}'")

    return cfg
