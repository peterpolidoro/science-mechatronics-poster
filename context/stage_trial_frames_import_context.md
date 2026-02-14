# Stage Trial Frames Asset: Import + Orientation Context

This document explains a simple, reproducible workflow for **importing the generated “trial stage frames” `.blend` asset** into another Blender scene (e.g., your poster scene) using:

- a small **JSON manifest** that describes *what to import* and *how to place it*, and
- a **Python script** that performs the import and applies the placement/orientation.

The goal is that the imported asset lands in the target scene with the **same coordinate/orientation assumptions** used when generating the frames.

---

## What the generated asset contains

The build pipeline produces a derived `.blend` (for example: `trial_stage_frames.blend`) that contains one or more top-level collections such as:

- `TRIAL_STAGE__stacked` – multiple instances stacked in the same place (or nearly so)
- `TRIAL_STAGE__timez` – multiple instances translated along **+Z** as time increases

Each “frame instance” includes the stage rig:

- `RIG_STAGE_ROOT`
  - `RIG_STAGE_YAW_AXIS`
    - `RIG_STAGE_PITCH_AXIS`
      - stage geometry (children)

### Orientation/rig assumptions used in the generator

When the frames were generated, we assumed:

1. **No extra world-space reorientation was applied.**  
   The asset keeps the *native* orientation authored in `joystick.blend` (`EXPORT_stage`).

2. **Yaw and pitch are applied as *delta rotations* about each empty’s local axis.**  
   - Yaw is applied to `RIG_STAGE_YAW_AXIS`
   - Pitch is applied to `RIG_STAGE_PITCH_AXIS`
   - In the generator we apply yaw/pitch as a **delta about each empty’s local Z axis** (quaternion multiply of a stored “base” orientation).

3. **Blender world up is +Z.**  
   In the `timez` layout, time progression is represented by translating instances along **+Z**.

**What this means for importing/orienting:**
- Do **not** edit the internal yaw/pitch rig empties when placing the asset in your poster scene.
- If you need to rotate/translate/scale the whole stack, do it *above* the rig:
  - using a “collection instance” object, or
  - by parenting the frame roots to a new empty and transforming that empty.

---

## Recommended import approach (cleanest): Collection Instance wrapper

Blender collections themselves do not have transforms, but a **Collection Instance** object does.  
This is the cleanest way to:

- move/rotate/scale the entire imported stack as one object,
- keep the internal parenting/rig intact,
- and avoid accidentally moving some objects but not others.

### Important note about visibility
If you append a collection and then also create a Collection Instance of it, you’ll see **two copies** unless you hide the original collection in the view layer.

The import script below handles this by optionally hiding the source collection.

---

## Import manifest (example)

Create an import manifest such as `stage_stack_import_manifest.json`:

```json
{
  "append_from_blend": "PATH/TO/trial_stage_frames.blend",
  "collections": ["TRIAL_STAGE__timez"],

  "instance_mode": "collection_instance",
  "hide_source_collections": true,

  "root_name": "STAGE_TRIAL_STACK",
  "target_scene_collection": "Collection",

  "transform": {
    "location": [0.0, 0.0, 0.0],
    "rotation_euler_deg": [0.0, 0.0, 0.0],
    "scale": [1.0, 1.0, 1.0]
  }
}
```

### Notes
- `collections` can be `["TRIAL_STAGE__stacked"]`, `["TRIAL_STAGE__timez"]`, or both.
- `rotation_euler_deg` is applied to the wrapper object (the instance root), not the rig.
- If you rotate the instance root, the local yaw/pitch axes rotate with it, which is typically what you want.

---

## Import Python script (example)

Save as `import_stage_stack.py` and run in the **target** `.blend` (poster scene) via CLI or Blender’s text editor.

```python
import json
import math
import bpy
from pathlib import Path


def append_collections(blend_path: str, collection_names: list[str]) -> list[bpy.types.Collection]:
    """Append specific collections from an external .blend and return the appended collections."""
    blend_path = str(Path(blend_path).expanduser())

    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        missing = [c for c in collection_names if c not in data_from.collections]
        if missing:
            raise RuntimeError(f"Collections not found in {blend_path}: {missing}\nAvailable: {list(data_from.collections)}")
        data_to.collections = collection_names

    # data_to.collections are appended into bpy.data.collections with same names
    return [bpy.data.collections[name] for name in collection_names]


def ensure_target_collection(name: str) -> bpy.types.Collection:
    """Get or create a collection in the current scene where imports will be linked."""
    scene = bpy.context.scene
    # If the scene already has a collection with this name, use it
    for c in scene.collection.children:
        if c.name == name:
            return c
    # Otherwise create it
    new_c = bpy.data.collections.new(name)
    scene.collection.children.link(new_c)
    return new_c


def set_transform(obj: bpy.types.Object, loc, rot_deg, scale):
    obj.location = loc
    obj.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    obj.scale = scale


def hide_collection_in_viewlayer(coll: bpy.types.Collection, hide: bool = True):
    """Disable a collection in the active view layer (viewport + render)."""
    view_layer = bpy.context.view_layer

    def recurse(layer_coll):
        if layer_coll.collection == coll:
            layer_coll.exclude = hide
            return True
        for child in layer_coll.children:
            if recurse(child):
                return True
        return False

    recurse(view_layer.layer_collection)


def main(manifest_path: str):
    cfg = json.loads(Path(manifest_path).read_text())

    blend_path = cfg["append_from_blend"]
    coll_names = cfg["collections"]

    instance_mode = cfg.get("instance_mode", "collection_instance")
    hide_sources = bool(cfg.get("hide_source_collections", True))

    root_name = cfg.get("root_name", "STAGE_TRIAL_STACK")
    target_coll_name = cfg.get("target_scene_collection", "Collection")

    loc = cfg["transform"]["location"]
    rot_deg = cfg["transform"]["rotation_euler_deg"]
    scale = cfg["transform"]["scale"]

    # 1) Append the collections
    imported_colls = append_collections(blend_path, coll_names)

    # 2) Link imported collections to the target scene collection
    target_coll = ensure_target_collection(target_coll_name)
    for c in imported_colls:
        # If it is already linked, Blender will throw; guard it
        if c.name not in {cc.name for cc in target_coll.children}:
            target_coll.children.link(c)

    # 3) Place/orient them
    if instance_mode == "collection_instance":
        # Create a wrapper empty that instances (the first) imported collection.
        # If you import multiple collections, you can create one instance per collection or
        # create a parent empty + child instances.
        parent = bpy.data.objects.new(root_name, None)
        parent.empty_display_type = 'PLAIN_AXES'
        bpy.context.scene.collection.objects.link(parent)
        set_transform(parent, loc, rot_deg, scale)

        for c in imported_colls:
            inst = bpy.data.objects.new(f"{root_name}__INST__{c.name}", None)
            inst.empty_display_type = 'PLAIN_AXES'
            inst.instance_type = 'COLLECTION'
            inst.instance_collection = c
            inst.parent = parent
            bpy.context.scene.collection.objects.link(inst)

            # Optionally hide the source collection so only the instance is visible
            if hide_sources:
                hide_collection_in_viewlayer(c, hide=True)

    elif instance_mode == "direct":
        # Direct approach: do not instance. Instead, create a root empty and parent the
        # top-level objects of the imported collections to it (keeping internal parenting).
        root = bpy.data.objects.new(root_name, None)
        root.empty_display_type = 'PLAIN_AXES'
        bpy.context.scene.collection.objects.link(root)
        set_transform(root, loc, rot_deg, scale)

        for c in imported_colls:
            for obj in list(c.objects):
                if obj.parent is None:
                    obj.parent = root
    else:
        raise ValueError(f"Unknown instance_mode: {instance_mode}")


if __name__ == "__main__":
    # Example usage in Blender's Text Editor:
    # main("/absolute/path/to/stage_stack_import_manifest.json")
    #
    # Or from CLI:
    # blender poster.blend --background --python import_stage_stack.py -- /path/to/manifest.json
    import sys
    argv = sys.argv
    if "--" in argv:
        manifest = argv[argv.index("--") + 1]
        main(manifest)
    else:
        raise RuntimeError("Pass manifest path after --")
```

---

## How to orient the imported asset correctly

Because the generator applied yaw/pitch as **local-axis deltas inside the rig**, the safe rule is:

> **Place and orient at the wrapper/root level. Do not rotate the yaw/pitch rig empties.**

### Typical placement pattern
- Keep the imported collection(s) untouched.
- Rotate/translate the wrapper empty (`STAGE_TRIAL_STACK`) to fit your poster’s layout.
- If you want “time goes upward” (for the `timez` stack), keep the wrapper’s Z axis pointing upward.

---

## Tips to keep the final frame visually dominant (optional)

If you are using a ghost trail:
- Put the **final frame** in its own collection or make sure its materials are **Opaque**.
- For Eevee, prefer ghost transparency with:
  - `blend_method = BLEND` (ghost does not occlude depth),
  - `shadow_method = NONE`,
  so the final pose remains easy to see.

This is best handled in the *generator* manifest/script, but the import approach (two view layers + compositor) is another robust option in the poster file.

---

## Summary

- Use a **placement/import manifest** to define:
  - which collections to append,
  - whether to instance them,
  - and the root transform (location/rotation/scale).
- Use a short **import script** to do the append and placement identically every time.
- Keep rig behavior consistent by transforming **above** the rig (wrapper/root), not inside the stage rig empties.
