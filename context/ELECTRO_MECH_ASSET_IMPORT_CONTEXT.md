# Electrical–Mechanical Corner Asset: Import & Orientation Context

This document explains how the **electrical–mechanical corner asset** (a compiled `.blend` file containing an `EXPORT_*` collection) can be imported into another Blender scene using a **JSON manifest + Python builder script**, and how to keep the asset oriented as assumed during authoring.

The intent is that the asset can be reused as a “scene fragment” inside a poster scene (or any other Blender scene) by instancing the exported collection.

---

## What the compiled asset contains

The compiled asset `.blend` (for example: `assets/compiled/blend/motion.blend`) contains a single **export collection** (for example: `EXPORT_motion`) which holds:

- **Left wall image** on the **XZ plane**:
  - The wall lies on `Y = 0`
  - The image occupies **+X and +Z**
  - The **corner of the image is anchored at the origin** `(0,0,0)`
  - The plane is authored so its **front face points toward +Y** (toward the intended camera position)

- **Right wall image** on the **YZ plane**:
  - The wall lies on `X = 0`
  - The image occupies **+Y and +Z**
  - The **corner of the image is anchored at the origin** `(0,0,0)`
  - The plane’s front face points toward **+X**

- **Optional center image**:
  - A billboard-like image plane whose normal is parallel to the “isometric camera plane” (see below)
  - Typically placed above the wall images so it is visible “over” them

- **Four optional component instances** on the **XY plane** (`Z = 0`):
  - left electrical, left mechanical, right electrical, right mechanical
  - These are usually *collection instances* loaded from `pcb.blend` / `joystick.blend` export collections.

The asset does **not** need to contain a camera or lights. It is designed to be imported into another scene which already owns camera/lights.

---

## Units assumption (important)

The asset is built assuming:

- **1 Blender Unit (BU) = 1 mm**
- `scene.unit_settings.scale_length = 0.001`

The poster repo’s builder (`poster/blendlib.py`) uses the same convention.

If you import this asset into a “default Blender units” scene where 1 BU = 1 meter, the asset will appear 1000× too large/small unless you compensate with a scale factor.

---

## Orientation assumption (“how it should look”)

During authoring we assumed the *viewer/camera* is located in the **(+X, +Y, +Z)** octant of the asset coordinate system and is looking at the origin.

### Intended camera direction
- Direction **from the origin to the camera**: proportional to **`(1, 1, 1)`**
- Direction **from the camera to the origin**: proportional to **`(-1, -1, -1)`**

### What you should see from that view
When viewed from that direction:

- The **XZ wall (Y=0)** appears on the **left**
- The **YZ wall (X=0)** appears on the **right**
- The **XY plane** is the “floor” at the bottom
- **+Z** goes up
- **+X** points down-left toward the camera
- **+Y** points down-right toward the camera

This is the classic “looking into the corner” view where the three axes appear 120° apart.

---

## Importing into the poster scene using a manifest entry

If you are using the poster repo’s builder (`poster/blendlib.py`), the easiest way to import is to add an object entry in the poster manifest:

```jsonc
{
  "name": "motion_corner",
  "enabled": true,
  "kind": "import_blend",
  "collection": "WORLD",

  "filepath": "assets/compiled/blend/motion.blend",
  "blend_collection": "EXPORT_motion",

  "link": true,

  // Place the ASSET ORIGIN (the corner) in poster/world coordinates:
  "location_mm": [0.0, 0.0, 0.0],

  // Leave at zero to preserve the assumed orientation:
  "rotation_deg": [0.0, 0.0, 0.0],

  // Usually 1,1,1 for mm scenes:
  "scale": [1.0, 1.0, 1.0]
}
```

### Notes
- `filepath` points to the compiled `.blend`.
- `blend_collection` should be the export collection name you set when building the asset (e.g., `EXPORT_motion`, `EXPORT_force_brake`, …).
- The builder will create a hidden **root empty** (transform handle) and an **instance empty** that instantiates your exported collection.
- Re-running the poster build is safe: the importer clears and rebuilds the `ASSET_<name>` collection.

---

## Importing via a standalone Python script (minimal example)

If you want to import the asset without the poster builder, here is a minimal “load collection and instance it” snippet:

```python
import bpy
from pathlib import Path
from mathutils import Euler, Vector
import math

def instance_blend_collection(blend_path: str, collection_name: str, *,
                              location=(0,0,0), rotation_deg=(0,0,0), scale=(1,1,1),
                              link=True):
    blend_path = str(Path(blend_path).resolve())

    # Load collection datablock
    with bpy.data.libraries.load(blend_path, link=link) as (data_from, data_to):
        if collection_name not in data_from.collections:
            raise ValueError(f"Collection '{collection_name}' not found. Available: {list(data_from.collections)}")
        data_to.collections = [collection_name]
    coll = data_to.collections[0]

    # Create an instancer empty
    inst = bpy.data.objects.new(f"INST_{collection_name}", None)
    bpy.context.scene.collection.objects.link(inst)
    inst.instance_type = 'COLLECTION'
    inst.instance_collection = coll

    # Apply transform on the instancer
    inst.location = Vector(location)
    inst.rotation_euler = Euler([math.radians(v) for v in rotation_deg], 'XYZ')
    inst.scale = Vector(scale)

    return inst
```

This is the same concept the poster repo uses: a collection instance empty points to the external library collection.

---

## Ensuring the asset is oriented as authored

### Option A: Keep asset at rotation (0,0,0) and place the camera
If you want the “canonical corner view”, set your camera relative to the asset origin:

```python
import bpy
from mathutils import Vector
import math

origin = Vector((0,0,0))  # or the imported root empty location
d = 1200.0  # mm
cam = bpy.data.objects["Camera"]

# Put camera in +X,+Y,+Z direction
cam.location = origin + Vector((1,1,1)).normalized() * d

# Aim at origin (simple track-to)
direction = (origin - cam.location).normalized()
rot_quat = direction.to_track_quat('-Z', 'Y')  # camera looks down -Z
cam.rotation_euler = rot_quat.to_euler()
```

This view matches the assumptions used when laying out the walls.

### Option B: Keep your existing camera and rotate the asset to match
If your destination scene has a fixed camera, you can rotate the asset’s **root empty** so that the camera lies along the asset’s intended `(1,1,1)` direction.

A simple approach is:
1. Compute `v_world = (camera_location - asset_origin).normalized()`
2. Compute a quaternion that rotates `v_asset = (1,1,1).normalized()` to `v_world`
3. Apply that rotation to the asset root

You may also need to constrain “roll” so that +Z stays up, depending on your scene.

---

## Troubleshooting checklist

### “The asset looks mirrored / the left wall faces away”
- Check the wall plane’s **face orientation**:
  - In the viewport: Overlays → **Face Orientation**
  - Blue should be on the side facing the camera.

### “The asset is the right shape but the image corner is wrong”
- This is usually a UV flip (`flip_u` / `flip_v`) issue inside the asset builder manifest (for the asset’s own `images.left/right` blocks).

### “Nothing shows up after importing”
- Verify the import points to the correct collection name:
  - The compiled asset must contain `EXPORT_*`.
- If using library link, ensure paths are correct and accessible.

### “Scale is wildly wrong”
- Confirm both scenes use **1 BU = 1 mm**. If not, compensate with `scale` or a per-import `import_scale`.

---

## Quick reference: what to import

To import the asset into another scene you only need two values:

- **Blend file path**: `assets/compiled/blend/<something>.blend`
- **Export collection**: `EXPORT_<something>`

Everything else is positioned by transforming the instance root.
