import bpy
import os
import json
import math
from datetime import datetime

# If these exist, the dump will focus on them (and their contents).
# Otherwise it dumps the whole scene collection tree.
FOCUS_COLLECTIONS = [
    "EXPORT_joystick",
    "EXPORT_stage",
    "EXPORT_joystick_yaw_axis_transducers",
    "EXPORT_joystick_pitch_axis_transducers",
    "EXPORT_joystick_brake",
    "EXPORT_joystick_torque_sensor"
]

def _mat_to_list(m):
    return [[float(v) for v in row] for row in m]

def _safe_custom_props(obj):
    # Blender stores custom properties like a dict; ignore UI metadata.
    out = {}
    for k in obj.keys():
        if k == "_RNA_UI":
            continue
        try:
            v = obj[k]
            # JSON-safe primitives only
            if isinstance(v, (int, float, str, bool)) or v is None:
                out[k] = v
            else:
                out[k] = str(v)
        except Exception:
            pass
    return out

def _obj_to_dict(o):
    d = {
        "name": o.name,
        "type": o.type,
        "data_name": getattr(getattr(o, "data", None), "name", None),
        "parent": o.parent.name if o.parent else None,
        "children": [c.name for c in o.children],
        "users_collection": [c.name for c in o.users_collection],
        "hide_viewport": bool(o.hide_viewport),
        "hide_render": bool(o.hide_render),

        # Transforms (readable)
        "location": [float(v) for v in o.location],
        "rotation_mode": o.rotation_mode,
        "rotation_euler_deg": [float(math.degrees(v)) for v in o.rotation_euler],
        "rotation_quaternion": [float(v) for v in o.rotation_quaternion],
        "scale": [float(v) for v in o.scale],

        # Matrix (exact)
        "matrix_world": _mat_to_list(o.matrix_world),

        # Bounding box (local)
        "bound_box_local": [list(map(float, bb)) for bb in getattr(o, "bound_box", [])],

        "constraints": [
            {
                "name": c.name,
                "type": c.type,
                "target": getattr(c, "target", None).name if getattr(c, "target", None) else None,
                "subtarget": getattr(c, "subtarget", None) if hasattr(c, "subtarget") else None,
            }
            for c in o.constraints
        ],

        "custom_props": _safe_custom_props(o),
    }

    if o.type == "EMPTY":
        d["empty_display_type"] = getattr(o, "empty_display_type", None)
        d["empty_display_size"] = float(getattr(o, "empty_display_size", 0.0))

    if o.type == "MESH" and getattr(o, "data", None) is not None:
        try:
            d["mesh_vertex_count"] = len(o.data.vertices)
            d["mesh_face_count"] = len(o.data.polygons)
        except Exception:
            pass

    return d

def _collection_to_dict(col):
    return {
        "name": col.name,
        "objects": [{"name": o.name, "type": o.type} for o in col.objects],
        "children": [_collection_to_dict(c) for c in col.children],
    }

def _format_collection_tree(col, indent=0):
    lines = []
    lines.append("  " * indent + f"- {col.name}")
    for o in col.objects:
        lines.append("  " * (indent + 1) + f"* {o.name} ({o.type})")
    for c in col.children:
        lines.extend(_format_collection_tree(c, indent + 1))
    return lines

def _gather_objects_for_focus():
    found_focus = []
    for name in FOCUS_COLLECTIONS:
        if name in bpy.data.collections:
            found_focus.append(bpy.data.collections[name])

    if found_focus:
        objs = set()
        for c in found_focus:
            for o in c.all_objects:
                objs.add(o)
        return found_focus, sorted(list(objs), key=lambda x: x.name)

    # fallback: dump active scene
    scene = bpy.context.scene
    return [], sorted(list(scene.objects), key=lambda x: x.name)

def main():
    blend_path = bpy.data.filepath
    out_dir = os.path.dirname(blend_path) if blend_path else bpy.app.tempdir

    json_path = os.path.join(out_dir, "joystick_structure.json")
    md_path = os.path.join(out_dir, "joystick_structure.md")

    focus_cols, objs = _gather_objects_for_focus()

    if focus_cols:
        collection_roots = {_c.name: _collection_to_dict(_c) for _c in focus_cols}
        md_sections = []
        for c in focus_cols:
            md_sections.append(f"# Collection tree: {c.name}")
            md_sections.extend(_format_collection_tree(c))
            md_sections.append("")
        md_text = "\n".join(md_sections)
    else:
        root = bpy.context.scene.collection
        collection_roots = {"SCENE_COLLECTION_ROOT": _collection_to_dict(root)}
        md_text = "\n".join(["# Scene collection tree"] + _format_collection_tree(root) + [""])

    payload = {
        "generated_at": datetime.now().isoformat(),
        "blend_filepath": blend_path,
        "scene_name": bpy.context.scene.name if bpy.context.scene else None,
        "focus_collections": [c.name for c in focus_cols],
        "collections": collection_roots,
        "objects": [_obj_to_dict(o) for o in objs],
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print("Wrote:")
    print("  ", json_path)
    print("  ", md_path)

main()
