"""
build_trial_stage_frames_v2.py

Blender script to generate a "poster" style stage-motion stack by duplicating
EXPORT_stage many times and dialing yaw/pitch per frame from a JSON manifest.

Adds:
  - Ghost-trail transparency without overriding the original materials for the
    FINAL frame (so the last pose is fully opaque / visually dominant).
  - Ghost materials are per-original-material copies with a small node patch
    (Transparent + Mix Shader) driven by per-object Object Info color.
  - Optional (off by default): boolean "difference" trail, where each earlier
    frame subtracts all later frames so only the unique volume is shown.

Usage (recommended):
  blender --background --factory-startup \
    --python build_trial_stage_frames_v2.py -- \
    --manifest /path/to/manifest.json \
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
  - In Eevee, **Alpha Blend** materials do not write to depth (often desirable
    here so ghost frames don't occlude the final). This script defaults ghost
    materials to **Alpha Hashed** so alpha=1.0 behaves opaque.

Compatibility:
  - Blender versions differ in node IDs. "Separate RGB" may not be registered
    (RuntimeError: ShaderNodeSeparateRGB undefined). We feature-detect and use
    "Separate Color" (mode='RGB') instead when available.
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
    p.add_argument(
        "--layout",
        default="both",
        choices=["stacked", "timez", "both"],
        help="Which layout(s) to build",
    )
    p.add_argument(
        "--no_cleanup",
        action="store_true",
        help="Don't delete default objects (cube, camera, light) before building",
    )
    return p.parse_args(argv)


# ----------------------------
# Blender data helpers
# ----------------------------

def cleanup_default_scene():
    # Remove all objects from the current scene.
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove all collections except the master scene collection
    master = bpy.context.scene.collection
    for col in list(master.children):
        master.children.unlink(col)


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
# Ghost-trail material helpers
# ----------------------------

def _find_material_output_node(nt: bpy.types.NodeTree):
    for n in nt.nodes:
        if n.type == "OUTPUT_MATERIAL":
            return n
    return None


def _ensure_ghost_node_patch(mat: bpy.types.Material, cfg: dict):
    """
    Patch a material so its final Surface is:
        Mix(Transparent, OriginalSurface, fac = object_color_r)

    This is only applied to a COPY of an original material, never the original.
    """
    if not mat.use_nodes:
        mat.use_nodes = True

    nt = mat.node_tree
    out = _find_material_output_node(nt)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (400, 0)

    # If already patched (id prop marker), don't patch twice
    if mat.get("__ghost_patched__", False):
        return

    surf_in = out.inputs.get("Surface")
    if surf_in is None:
        # Weird material; give up gracefully
        mat["__ghost_patched__"] = True
        return

    # Find existing Surface link (Original shader output)
    orig_link = surf_in.links[0] if surf_in.links else None
    orig_socket = orig_link.from_socket if orig_link else None

    # Build nodes
    obj_info = nt.nodes.new("ShaderNodeObjectInfo")
    obj_info.location = (0, -200)

    # NOTE (Blender 3.3+ / 4.x / 5.x): "Separate RGB" was replaced in the UI
    # by "Separate Color" (mode='RGB'). Some versions/builds no longer
    # register ShaderNodeSeparateRGB, which causes:
    #   RuntimeError: Node type ShaderNodeSeparateRGB undefined
    # So we feature-detect and fall back.
    sep_rgb = None
    sep_in = None
    sep_out_r = None
    try:
        sep_rgb = nt.nodes.new("ShaderNodeSeparateColor")
        # Ensure RGB channel split.
        if hasattr(sep_rgb, "mode"):
            try:
                sep_rgb.mode = "RGB"
            except Exception:
                pass
        # Shader node uses a Color input socket.
        sep_in = sep_rgb.inputs.get("Color") or sep_rgb.inputs.get("Image")
        sep_out_r = sep_rgb.outputs.get("R") or sep_rgb.outputs.get("Red")
    except Exception:
        sep_rgb = nt.nodes.new("ShaderNodeSeparateRGB")
        sep_in = sep_rgb.inputs.get("Image")
        sep_out_r = sep_rgb.outputs.get("R")

    sep_rgb.location = (200, -200)
    # Extra safety for socket name differences.
    if sep_in is None and len(sep_rgb.inputs):
        sep_in = sep_rgb.inputs[0]
    if sep_out_r is None and len(sep_rgb.outputs):
        sep_out_r = sep_rgb.outputs[0]

    bsdf_transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    bsdf_transp.location = (200, 80)

    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (600, 0)

    # Wire: ObjectInfo.Color -> SeparateRGB -> R -> Mix.Fac
    nt.links.new(obj_info.outputs.get("Color"), sep_in)
    nt.links.new(sep_out_r, mix.inputs.get("Fac"))

    # Wire: Transparent -> Mix.Shader(1)
    nt.links.new(bsdf_transp.outputs.get("BSDF"), mix.inputs[1])

    # Wire: Original -> Mix.Shader(2) if possible, else create Principled
    if orig_socket is None:
        principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (200, 0)
        orig_socket = principled.outputs.get("BSDF")
    else:
        # Disconnect original from output
        try:
            nt.links.remove(orig_link)
        except Exception:
            pass

    nt.links.new(orig_socket, mix.inputs[2])
    nt.links.new(mix.outputs.get("Shader"), surf_in)

    # Render settings for transparency in Eevee
    # NOTE: blend_method affects depth-write behavior.
    blend_method = str(cfg.get("blend_method", "HASHED")).upper()
    if blend_method not in {"OPAQUE", "CLIP", "HASHED", "BLEND"}:
        blend_method = "HASHED"

    try:
        mat.blend_method = blend_method
    except Exception:
        pass

    # Shadows: often cleaner to disable or use hashed
    shadow_method = str(cfg.get("shadow_method", "HASHED")).upper()
    try:
        mat.shadow_method = shadow_method
    except Exception:
        pass

    # Backface culling can reduce "see-through interior" clutter for ghosts
    try:
        mat.use_backface_culling = bool(cfg.get("use_backface_culling", True))
    except Exception:
        pass

    mat["__ghost_patched__"] = True


def get_or_create_ghost_material(orig: bpy.types.Material, cache: dict, cfg: dict) -> bpy.types.Material:
    if orig is None:
        return None
    if orig in cache:
        return cache[orig]

    ghost = orig.copy()
    ghost.name = f"{orig.name}{cfg.get('suffix', '__ghost')}"
    _ensure_ghost_node_patch(ghost, cfg)

    cache[orig] = ghost
    return ghost


def assign_ghost_materials(obj: bpy.types.Object, mat_cache: dict, cfg: dict):
    if obj.type != "MESH":
        return
    # Swap each material slot for its ghost copy
    for slot in obj.material_slots:
        m = slot.material
        if m is None:
            continue
        slot.material = get_or_create_ghost_material(m, mat_cache, cfg)


# ----------------------------
# Optional boolean "difference" helpers
# ----------------------------

def _boolean_collection_supported() -> bool:
    # Blender versions differ; feature-detect with a dummy modifier
    try:
        tmp = bpy.data.objects.new("__tmp__", None)
        bpy.context.scene.collection.objects.link(tmp)
        mod = tmp.modifiers.new("tmp_bool", type="BOOLEAN")
        ok = hasattr(mod, "operand_type")
        # cleanup
        bpy.data.objects.remove(tmp, do_unlink=True)
        return ok
    except Exception:
        try:
            bpy.data.objects.remove(tmp, do_unlink=True)
        except Exception:
            pass
        return False


def add_boolean_difference_to_frame(
    frame_mesh_objects: list,
    subtract_collection: bpy.types.Collection,
    cfg: dict,
):
    """
    Add a BOOLEAN(DIFFERENCE) modifier to each mesh object in frame_mesh_objects
    using subtract_collection as the operand (when supported).
    """
    solver = str(cfg.get("solver", "EXACT")).upper()

    for obj in frame_mesh_objects:
        if obj.type != "MESH":
            continue
        mod = obj.modifiers.new(name="TRAIL_DIFF", type="BOOLEAN")
        try:
            mod.operation = "DIFFERENCE"
        except Exception:
            pass

        # Prefer collection operands if available; else fall back to first object.
        if hasattr(mod, "operand_type"):
            try:
                mod.operand_type = "COLLECTION"
                mod.collection = subtract_collection
            except Exception:
                pass
        else:
            # Old blender: only single object operand
            first = None
            for o in subtract_collection.objects:
                if o.type == "MESH":
                    first = o
                    break
            if first is not None:
                try:
                    mod.object = first
                except Exception:
                    pass

        # Solver setting (not present in all versions)
        if hasattr(mod, "solver"):
            try:
                mod.solver = solver
            except Exception:
                pass


# ----------------------------
# Main build
# ----------------------------

def build_layout(
    layout_name: str,
    export_collection: bpy.types.Collection,
    stage_objs: list,
    rig_names: dict,
    frames: list,
    ghost_cfg: dict,
    base_location=(0.0, 0.0, 0.0),
    z_span_factor: float = 0.0,
):
    """
    Create one layout collection with per-frame duplicated stages.

    Structure:
      TRIAL_STAGE__{layout}
        ├── GHOST
        │    ├── {layout}__F000__...
        │    └── ...
        └── FINAL
             └── {layout}__F###__...
    """
    top = bpy.data.collections.new(f"TRIAL_STAGE__{layout_name}")
    bpy.context.scene.collection.children.link(top)

    col_ghost = bpy.data.collections.new(f"{layout_name}__GHOST")
    col_final = bpy.data.collections.new(f"{layout_name}__FINAL")
    top.children.link(col_ghost)
    top.children.link(col_final)

    # Find template rig objects by name inside the appended stage set
    tmpl_root = next((o for o in stage_objs if o.name == rig_names["root_name"]), None)
    tmpl_yaw = next((o for o in stage_objs if o.name == rig_names["yaw_name"]), None)
    tmpl_pitch = next((o for o in stage_objs if o.name == rig_names["pitch_name"]), None)

    if tmpl_root is None or tmpl_yaw is None or tmpl_pitch is None:
        raise RuntimeError(
            "Could not find one or more rig empties in the appended stage. "
            f"Needed: {rig_names}. Found root={tmpl_root}, yaw={tmpl_yaw}, pitch={tmpl_pitch}"
        )

    frames_sorted = sorted(frames, key=lambda f: int(f["frame"]))
    n = len(frames_sorted)
    last_frame_id = int(frames_sorted[-1]["frame"]) if n else 0

    # Compute Z span from geometry so the "time as Z" spacing adapts to asset scale
    z_total = 0.0
    if z_span_factor and z_span_factor != 0.0:
        z_span = compute_world_bbox_z_span(stage_objs)
        z_total = z_span * float(z_span_factor)

    # Ghost settings
    ghost_enabled = bool(ghost_cfg.get("enabled", False))
    alpha_first = float(ghost_cfg.get("alpha_first", 0.15))
    # The manifest originally used alpha_pre_last (meaning: the last GHOST frame).
    # Accept alpha_last as an alias because it's easy to misremember.
    alpha_pre_last = float(
        ghost_cfg.get("alpha_pre_last", ghost_cfg.get("alpha_last", 0.85))
    )
    # Material behavior
    ghost_mat_cfg = {
        "blend_method": ghost_cfg.get("blend_method", "HASHED"),
        "shadow_method": ghost_cfg.get("shadow_method", "HASHED"),
        "use_backface_culling": ghost_cfg.get("use_backface_culling", True),
        "suffix": ghost_cfg.get("material_suffix", "__ghost"),
    }
    use_material_copies = bool(ghost_cfg.get("use_material_copies", True))
    final_uses_original_materials = bool(ghost_cfg.get("final_uses_original_materials", True))

    # Optional: hide some objects in ghost frames by name match
    hide_name_contains = [str(s) for s in ghost_cfg.get("ghost_hide_name_contains", [])]

    # Optional: boolean difference
    diff_cfg = ghost_cfg.get("difference_boolean", {}) or {}
    diff_enabled = bool(diff_cfg.get("enabled", False))

    ghost_material_cache = {}

    # Keep references to per-frame mesh objects for optional boolean logic
    per_frame_mesh_objects = {}  # frame_id -> [mesh objs]
    per_frame_col = {}           # frame_id -> frame collection

    # Precompute alpha per frame (by order, not absolute frame_id gaps)
    alpha_by_frame = {}
    if ghost_enabled and n >= 1:
        if n == 1:
            alpha_by_frame[int(frames_sorted[0]["frame"])] = 1.0
        elif n == 2:
            # 1 ghost + final
            alpha_by_frame[int(frames_sorted[0]["frame"])] = alpha_first
            alpha_by_frame[int(frames_sorted[1]["frame"])] = 1.0
        else:
            for i, fr in enumerate(frames_sorted):
                fid = int(fr["frame"])
                if i == n - 1:
                    alpha = 1.0
                else:
                    # map i in [0, n-2] => alpha in [alpha_first, alpha_pre_last]
                    t = i / max(1, (n - 2))
                    alpha = alpha_first + t * (alpha_pre_last - alpha_first)
                alpha_by_frame[fid] = float(alpha)
    else:
        for fr in frames_sorted:
            alpha_by_frame[int(fr["frame"])] = 1.0

    # Build frames
    for fr in frames_sorted:
        idx = int(fr["frame"])
        is_last = idx == last_frame_id

        parent_col = col_final if is_last else col_ghost

        frame_col = bpy.data.collections.new(f"{layout_name}__F{idx:03d}__{fr.get('phase','')}")
        parent_col.children.link(frame_col)
        per_frame_col[idx] = frame_col

        mapping = duplicate_objects_linked(stage_objs, frame_col)

        # Rename the 3 main rig empties for clarity
        inst_root = mapping[tmpl_root]
        inst_yaw = mapping[tmpl_yaw]
        inst_pitch = mapping[tmpl_pitch]
        inst_root.name = f"{rig_names['root_name']}__{layout_name}__F{idx:03d}"
        inst_yaw.name = f"{rig_names['yaw_name']}__{layout_name}__F{idx:03d}"
        inst_pitch.name = f"{rig_names['pitch_name']}__{layout_name}__F{idx:03d}"

        # Place the whole stage
        z_off = 0.0
        if z_total and n > 1:
            # normalized by ORDER, not absolute frame id
            order_i = next((i for i, ff in enumerate(frames_sorted) if int(ff["frame"]) == idx), 0)
            z_off = z_total * (order_i / (n - 1))

        inst_root.location = Vector(base_location) + Vector((0.0, 0.0, z_off))

        # Stash useful per-frame metadata
        inst_root["frame"] = idx
        inst_root["t_norm"] = float(fr.get("t_norm", idx / max(1, n - 1)))
        inst_root["phase"] = fr.get("phase", "")
        inst_root["yaw_deg"] = float(fr.get("yaw_deg", 0.0))
        inst_root["pitch_deg"] = float(fr.get("pitch_deg", 0.0))

        # Apply yaw/pitch deltas
        apply_local_z_delta_deg(
            inst_yaw,
            float(fr.get("yaw_deg", 0.0)) * float(rig_names.get("yaw_sign", 1.0)),
        )
        apply_local_z_delta_deg(
            inst_pitch,
            float(fr.get("pitch_deg", 0.0)) * float(rig_names.get("pitch_sign", 1.0)),
        )

        # Apply ghost alpha/materials to duplicated objects (not the template)
        alpha = float(alpha_by_frame.get(idx, 1.0))

        frame_meshes = []
        for old, new in mapping.items():
            if new.type != "MESH":
                continue

            # Optional: hide certain objects in ghost frames to reduce clutter
            if (not is_last) and hide_name_contains:
                nm = new.name.lower()
                if any(s.lower() in nm for s in hide_name_contains):
                    new.hide_render = True
                    new.hide_viewport = True
                    continue

            frame_meshes.append(new)

            if ghost_enabled:
                new["ghost_alpha"] = alpha
                # Use RGB = alpha so ObjectInfo.Color.R carries the alpha scalar.
                try:
                    new.color = (alpha, alpha, alpha, 1.0)
                except Exception:
                    pass

                if (not is_last) and use_material_copies:
                    assign_ghost_materials(new, ghost_material_cache, ghost_mat_cfg)

                if is_last and final_uses_original_materials:
                    # Make sure final frame is not accidentally using ghost materials
                    # (e.g., if user disabled material copies). Ensure object color is white.
                    try:
                        new.color = (1.0, 1.0, 1.0, 1.0)
                    except Exception:
                        pass

        per_frame_mesh_objects[idx] = frame_meshes

    # Optional: boolean difference (unique volume trail)
    if ghost_enabled and diff_enabled and n >= 2:
        # Build "subtract collections" for each ghost frame:
        #   SUBTRACT_AFTER_Fi contains all mesh objects from frames with id > i
        # Then add BOOLEAN(DIFFERENCE) modifiers to frame i mesh objects.
        col_bool = bpy.data.collections.new(f"{layout_name}__BOOL_SUBTRACT")
        top.children.link(col_bool)
        col_bool.hide_viewport = True
        col_bool.hide_render = True

        # Determine ordered frame ids
        frame_ids = [int(fr["frame"]) for fr in frames_sorted]

        for i, fid in enumerate(frame_ids[:-1]):  # exclude final
            sub = bpy.data.collections.new(f"SUBTRACT_AFTER__F{fid:03d}")
            col_bool.children.link(sub)
            # link all later meshes into the operand collection
            for later_fid in frame_ids[i + 1 :]:
                for o in per_frame_mesh_objects.get(later_fid, []):
                    try:
                        sub.objects.link(o)
                    except Exception:
                        pass

            add_boolean_difference_to_frame(
                per_frame_mesh_objects.get(fid, []),
                sub,
                diff_cfg,
            )

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

    ghost_cfg = manifest.get("ghost_trail", {}) or {}

    export_col = append_export_collection(source["blend_path"], source["export_collection"])

    # Collect ALL objects under the appended export collection (recursively)
    stage_objs = list(iter_collection_objects_recursive(export_col))

    # Hide the appended template export in renders (kept as a hidden template)
    export_col.hide_viewport = True
    export_col.hide_render = True

    want_stacked = args.layout in ("stacked", "both")
    want_timez = args.layout in ("timez", "both")

    rig_cfg = {**rig, **{"yaw_sign": rig.get("yaw_sign", 1.0), "pitch_sign": rig.get("pitch_sign", 1.0)}}

    if want_stacked and layouts.get("stacked", {}).get("enabled", True):
        build_layout(
            "stacked",
            export_col,
            stage_objs,
            rig_cfg,
            frames,
            ghost_cfg,
            base_location=layouts.get("stacked", {}).get("base_location", (0.0, 0.0, 0.0)),
            z_span_factor=float(layouts.get("stacked", {}).get("z_span_factor", 0.0)),
        )

    if want_timez and layouts.get("timez", {}).get("enabled", True):
        build_layout(
            "timez",
            export_col,
            stage_objs,
            rig_cfg,
            frames,
            ghost_cfg,
            base_location=layouts.get("timez", {}).get("base_location", (0.0, 0.0, 0.0)),
            z_span_factor=float(layouts.get("timez", {}).get("z_span_factor", 0.05)),
        )

    out_path = bpy.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
