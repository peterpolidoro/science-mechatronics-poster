"""poster/blendlib.py

Shared Blender-Python utilities used by open.py and render.py.

Design goals:
- Declarative control via poster/manifest.json
- Deterministic object naming (objects addressed by name)
- mm-based workflow (1 Blender unit = 1 mm)
- Perspective camera + camera-attached poster plane for mm-accurate overlays
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from mathutils import Euler, Vector


# ----------------------------
# Small helpers
# ----------------------------

def load_manifest(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def abspath_from_manifest(manifest_path: str | Path, maybe_rel: str | Path) -> str:
    mp = Path(manifest_path).resolve()
    p = Path(maybe_rel)
    if p.is_absolute():
        return str(p)
    return str((mp.parent / p).resolve())

def ensure_collection(name: str) -> bpy.types.Collection:
    scene = bpy.context.scene
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)

    # Ensure the collection is linked to the active scene.
    # Use `.get()` because bpy_prop_collections are name-addressable.
    if scene.collection.children.get(col.name) is None:
        try:
            scene.collection.children.link(col)
        except RuntimeError:
            # Already linked somewhere else in the scene graph.
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

def remove_collection_objects(col: bpy.types.Collection) -> None:
    # Remove objects from the scene and datablocks
    objs = list(col.objects)
    for obj in objs:
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

def set_world_transform(obj: bpy.types.Object,
                        location_mm: Sequence[float],
                        rotation_deg: Sequence[float],
                        scale_xyz: Sequence[float]) -> None:
    obj.location = Vector(location_mm)
    obj.rotation_euler = Euler([math.radians(v) for v in rotation_deg], 'XYZ')
    obj.scale = Vector(scale_xyz)

def ensure_plane_mesh(mesh_name: str) -> bpy.types.Mesh:
    # 1x1 plane centered at origin, lying on XY
    mesh = bpy.data.meshes.get(mesh_name)
    if mesh is None:
        mesh = bpy.data.meshes.new(mesh_name)
        verts = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
    return mesh

def ensure_material_solid(name: str, rgba: Sequence[float]) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (rgba[0], rgba[1], rgba[2], rgba[3])
        bsdf.inputs["Roughness"].default_value = 0.55
    return mat

def ensure_material_image(name: str, image_path: str) -> bpy.types.Material:
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
    out.location = (380, 0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (120, 0)
    bsdf.inputs["Roughness"].default_value = 1.0

    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-220, 0)
    img = bpy.data.images.load(image_path, check_existing=True)
    tex.image = img

    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    # If alpha exists, use it
    if "Alpha" in tex.outputs:
        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])

    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Eevee transparency-friendly defaults
    mat.blend_method = 'CLIP'
    mat.shadow_method = 'CLIP'
    return mat


# ----------------------------
# Poster math
# ----------------------------

def poster_plane_distance_mm(poster_size_mm: float, lens_mm: float, sensor_width_mm: float) -> float:
    # For a square render and horizontal sensor fit:
    # width = d * sensor_width / lens  =>  d = width * lens / sensor_width
    return poster_size_mm * lens_mm / sensor_width_mm

def place_on_poster_plane(obj: bpy.types.Object,
                          cam_obj: bpy.types.Object,
                          plane_distance_mm: float,
                          poster_xy_mm: Sequence[float],
                          z_mm: float) -> None:
    # Parent to camera so it remains parallel to the camera sensor.
    obj.parent = cam_obj
    obj.matrix_parent_inverse = cam_obj.matrix_world.inverted()

    # In camera local space:
    # -X left, +X right
    # -Y down, +Y up
    # Z points along camera view axis (negative is "in front" of camera)
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

def apply_render_settings(cfg: Dict[str, Any],
                          poster_in: float,
                          ppi_override: Optional[float] = None) -> None:
    scene = bpy.context.scene

    r = cfg.get("render", {})
    engine_pref = r.get("engine_preference", ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"])
    for eng in engine_pref:
        try:
            scene.render.engine = eng
            break
        except Exception:
            continue

    view_transform = r.get("view_transform", "Standard")
    try:
        scene.view_settings.view_transform = view_transform
    except Exception:
        pass

    scene.render.film_transparent = bool(r.get("film_transparent", False))

    file_format = r.get("file_format", "PNG")
    scene.render.image_settings.file_format = file_format
    scene.render.image_settings.color_mode = r.get("color_mode", "RGBA")
    scene.render.image_settings.color_depth = str(r.get("color_depth", "16"))

    ppi = float(ppi_override) if ppi_override is not None else float(cfg.get("poster", {}).get("ppi", 150))
    res = int(round(poster_in * ppi))
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.resolution_percentage = 100

def ensure_camera_and_guides(cfg: Dict[str, Any]) -> Tuple[bpy.types.Object, float]:
    scene = bpy.context.scene
    poster = cfg.get("poster", {})
    cam_cfg = cfg.get("camera", {})

    poster_mm = float(poster.get("size_mm", 1219.2))
    safe_margin_mm = float(poster.get("safe_margin_mm", 25.4))

    cam = ensure_camera(cam_cfg.get("name", "CAM_Poster"))
    cam.data.type = 'PERSP'
    cam.data.lens = float(cam_cfg.get("lens_mm", 85.0))
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.sensor_width = float(cam_cfg.get("sensor_width_mm", 36.0))

    cam.location = Vector(cam_cfg.get("location_mm", [0.0, -3500.0, 1500.0]))

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

    # Compute poster plane distance and create guide planes parented to camera
    d_mm = poster_plane_distance_mm(poster_mm, cam.data.lens, cam.data.sensor_width)

    helpers = ensure_collection("HELPERS")

    # Poster plane (wireframe, hidden in renders)
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
    plane.scale = Vector((poster_mm, poster_mm, 1.0))

    # Safe area guide
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
    safe.location = Vector((0.0, 0.0, -d_mm + 0.5))  # tiny offset toward camera
    safe.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')
    safe_size = max(1.0, poster_mm - 2.0 * safe_margin_mm)
    safe.scale = Vector((safe_size, safe_size, 1.0))

    return cam, d_mm

def apply_light_rig(cfg: Dict[str, Any]) -> None:
    lights_cfg = cfg.get("lights", {})
    if not lights_cfg.get("enabled", True):
        return

    lights_col = ensure_collection("LIGHTS")

    def ensure_area_light(name: str, loc_mm: Sequence[float], energy: float, size_mm: float) -> bpy.types.Object:
        obj = bpy.data.objects.get(name)
        if obj is None:
            light_data = bpy.data.lights.new(name + "_DATA", type='AREA')
            obj = bpy.data.objects.new(name, light_data)
            bpy.context.scene.collection.objects.link(obj)
        obj.location = Vector(loc_mm)
        obj.data.energy = float(energy)
        obj.data.size = float(size_mm)
        move_object_to_collection(obj, lights_col)
        return obj

    rig = lights_cfg.get("rig", "three_area")
    if rig == "three_area":
        k = lights_cfg.get("key", {})
        f = lights_cfg.get("fill", {})
        r = lights_cfg.get("rim", {})
        ensure_area_light("LIGHT_Key",  k.get("location_mm", [2000, -1500, 3000]), k.get("energy", 2500), k.get("size_mm", 2500))
        ensure_area_light("LIGHT_Fill", f.get("location_mm", [-2500, -2500, 2000]), f.get("energy", 1200), f.get("size_mm", 3500))
        ensure_area_light("LIGHT_Rim",  r.get("location_mm", [0, 2500, 2500]), r.get("energy", 1800), r.get("size_mm", 3000))


# ----------------------------
# Object builders
# ----------------------------

def ensure_text_object(obj_cfg: Dict[str, Any],
                       manifest_path: str | Path,
                       styles: Dict[str, Any],
                       cam_obj: bpy.types.Object,
                       poster_plane_distance: float) -> bpy.types.Object:
    name = obj_cfg["name"]

    # Curve datablock
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
    style_name = obj_cfg.get("style", "")
    style = styles.get(style_name, {})

    # Size/extrusion: allow override per object, else fall back to style
    curve.size = float(obj_cfg.get("size_mm", style.get("size_mm", 20.0)))
    curve.extrude = float(obj_cfg.get("extrude_mm", style.get("extrude_mm", 0.0)))

    # Alignment
    if "align_x" in obj_cfg:
        try:
            curve.align_x = obj_cfg["align_x"]
        except Exception:
            pass

    # Font
    font_rel = obj_cfg.get("font", style.get("font"))
    if font_rel:
        font_path = abspath_from_manifest(manifest_path, font_rel)
        if os.path.exists(font_path):
            try:
                curve.font = bpy.data.fonts.load(font_path, check_existing=True)
            except Exception:
                pass

    # Material color
    rgba = obj_cfg.get("color_rgba", style.get("color_rgba"))
    if rgba:
        mat = ensure_material_solid("MAT_" + (style_name or name), rgba)
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

    # Placement
    if obj_cfg.get("space", "WORLD") == "POSTER":
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

def ensure_image_plane(obj_cfg: Dict[str, Any],
                       manifest_path: str | Path,
                       cam_obj: bpy.types.Object,
                       poster_plane_distance: float) -> bpy.types.Object:
    name = obj_cfg["name"]
    obj = bpy.data.objects.get(name)
    if obj is None:
        mesh = ensure_plane_mesh(name + "_MESH")
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)

    w_mm, h_mm = obj_cfg.get("size_mm", [100.0, 100.0])
    obj.scale = Vector((float(w_mm), float(h_mm), 1.0))

    img_path = abspath_from_manifest(manifest_path, obj_cfg["image_path"])
    mat = ensure_material_image("MAT_" + name, img_path)
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    if obj_cfg.get("space", "WORLD") == "POSTER":
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

def _set_active_object(obj: bpy.types.Object) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

def _import_objects_and_get_new(import_op) -> List[bpy.types.Object]:
    before = {o.name for o in bpy.data.objects}
    import_op()
    after = {o.name for o in bpy.data.objects}
    new_names = list(after - before)
    return [bpy.data.objects[n] for n in new_names if n in bpy.data.objects]

def ensure_imported_asset(obj_cfg: Dict[str, Any],
                          manifest_path: str | Path,
                          importer: str) -> bpy.types.Object:
    """Import a GLB/WRL and wrap it under a stable Empty root named obj_cfg['name'].

    Strategy:
    - Root object name is stable and used by other declarative items.
    - Imported child objects live in a dedicated collection 'ASSET_<name>'.
    - On each apply, the asset collection is cleared and the file is re-imported.
      (This keeps the result deterministic while allowing upstream asset changes.)
    """
    name = obj_cfg["name"]
    parent_collection_name = obj_cfg.get("collection", "WORLD")
    parent_col = ensure_collection(parent_collection_name)
    asset_col = ensure_child_collection(parent_col, f"ASSET_{name}")

    # Ensure root Empty exists (stable handle)
    root = bpy.data.objects.get(name)
    if root is None:
        root = bpy.data.objects.new(name, None)
        root.empty_display_type = 'PLAIN_AXES'
        bpy.context.scene.collection.objects.link(root)
    move_object_to_collection(root, parent_col)

    # Temporarily reset root transform so parenting doesn't surprise us
    desired_loc = obj_cfg.get("location_mm", [0.0, 0.0, 0.0])
    desired_rot = obj_cfg.get("rotation_deg", [0.0, 0.0, 0.0])
    desired_scale = obj_cfg.get("scale", [1.0, 1.0, 1.0])

    root.location = Vector((0.0, 0.0, 0.0))
    root.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')
    root.scale = Vector((1.0, 1.0, 1.0))

    # Clear previous imported children
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

    # Import and capture created objects
    try:
        new_objs = _import_objects_and_get_new(op)
    except Exception as e:
        raise RuntimeError(f"Import failed for {filepath}: {e}")

    # Optional post-import scale factor (useful for WRL unit normalization)
    import_scale = float(obj_cfg.get("import_scale", 1.0))
    if import_scale != 1.0:
        for o in new_objs:
            o.scale *= import_scale

    # Move into our asset collection and parent under root
    for o in new_objs:
        # Avoid parenting cameras/lights accidentally if an importer produces them
        if o.type in {"CAMERA", "LIGHT"}:
            continue
        move_object_to_collection(o, asset_col)
        o.parent = root
        o.matrix_parent_inverse = root.matrix_world.inverted()

    # Apply desired transform to root
    set_world_transform(root, desired_loc, desired_rot, desired_scale)
    return root


# ----------------------------
# Main entrypoint
# ----------------------------

def apply_manifest(manifest_path: str | Path,
                   *,
                   ppi_override: Optional[float] = None) -> Dict[str, Any]:
    cfg = load_manifest(manifest_path)

    # Top-level collections
    ensure_collection("WORLD")
    ensure_collection("OVERLAY")
    ensure_collection("HELPERS")
    ensure_collection("LIGHTS")

    apply_units(cfg)

    poster_mm = float(cfg.get("poster", {}).get("size_mm", 1219.2))
    poster_in = poster_mm / 25.4
    apply_render_settings(cfg, poster_in, ppi_override=ppi_override)

    cam, plane_d_mm = ensure_camera_and_guides(cfg)
    apply_light_rig(cfg)

    styles = cfg.get("styles", {})

    # Build objects
    for obj_cfg in cfg.get("objects", []):
        kind = obj_cfg.get("kind")
        collection_name = obj_cfg.get("collection", "WORLD")
        col = ensure_collection(collection_name)

        if kind == "text":
            obj = ensure_text_object(obj_cfg, manifest_path, styles, cam, plane_d_mm)
            move_object_to_collection(obj, col)

        elif kind == "image_plane":
            obj = ensure_image_plane(obj_cfg, manifest_path, cam, plane_d_mm)
            move_object_to_collection(obj, col)

        elif kind == "import_glb":
            obj = ensure_imported_asset(obj_cfg, manifest_path, importer="glb")
            move_object_to_collection(obj, col)

        elif kind == "import_wrl":
            obj = ensure_imported_asset(obj_cfg, manifest_path, importer="wrl")
            move_object_to_collection(obj, col)

        else:
            print(f"[WARN] Unknown kind '{kind}' for object '{obj_cfg.get('name')}'")

    return cfg
