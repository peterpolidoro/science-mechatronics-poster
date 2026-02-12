# Reusable Blender Assets: `joystick.blend` + `pcb.blend`

This document describes how the two asset files are organized so you can reliably **append/link** them into a separate Blender scene (your poster scene), and how to set the **Yaw/Pitch stage angles** for the 2‑axis mechanism.

---

## 1) Collection naming conventions (the “public API”)

Both `joystick.blend` and `pcb.blend` follow the same pattern:

### `EXPORT_*` collections (what you import)
- Treat these as the file’s **public entry points**.
- An `EXPORT_*` collection should contain **no objects directly**.
- It should contain **only child collections** (usually one `SRC_*` and one `RIG_*`).

### `SRC_*` collections (geometry / source objects)
- Contain the *actual meshes* (and often CAD-import empties).
- Generally: **do not animate or transform** objects here.

### `RIG_*` collections (the handles you transform)
- Contain only **rig empties** that you are allowed to move/rotate/scale.
- The `SRC_*` objects are parented under these rig empties so transforms propagate correctly.

---

## 2) `joystick.blend` exports

The current joystick export set includes these `EXPORT_*` collections:

### A) Full mechanical joystick assembly
- **`EXPORT_joystick`**
  - `SRC_joystick`
  - `RIG_joystick`

**Main rig handle (move/rotate/scale the whole joystick):**
- `RIG_JOYSTICK_ROOT`

**Stage rig (Yaw/Pitch) included inside the full joystick rig:**
- `RIG_STAGE_ROOT`
- `RIG_STAGE_YAW_AXIS`
- `RIG_STAGE_PITCH_AXIS`

### B) Stage-only export
- **`EXPORT_stage`**
  - `SRC_stage`
  - `RIG_stage`

Use this when you want **only the yaw/pitch stage** (for arrays, exploded views, etc.) without the rest of the mechanical assembly.

### C) Optional mechanical “exploded view” subsets
These exports are meant for placing functional units around the main assembly:

- **`EXPORT_joystick_yaw_axis_transducers`**
  - `SRC_joystick_yaw_axis_transducers`
  - `RIG_joystick_yaw_axis_transducers`

- **`EXPORT_joystick_pitch_axis_transducers`**
  - `SRC_joystick_pitch_axis_transducers`
  - `RIG_joystick_pitch_axis_transducers`

- **`EXPORT_joystick_brake`**
  - `SRC_joystick_brake`
  - `RIG_joystick_brake`

- **`EXPORT_joystick_torque_sensor`**
  - `SRC_joystick_torque_sensor`
  - `RIG_joystick_torque_sensor`

**Important:** These joystick subsets include the same stage rig empties (`RIG_STAGE_*`) so you can still dial yaw/pitch angles on the subset in isolation.

---

## 3) The 2‑axis stage rig (Yaw + Pitch)

### Rig empties
The stage is controlled by these empties:

- `RIG_STAGE_ROOT`
  - Root handle for the stage assembly/subset.
  - Use this for **placement transforms** (location / overall Z rotation / uniform scale).

- `RIG_STAGE_YAW_AXIS`
  - Rotating this sets the **Yaw** angle.

- `RIG_STAGE_PITCH_AXIS`
  - Rotating this sets the **Pitch** angle.

They are intended to be parented like:

`RIG_STAGE_ROOT  →  RIG_STAGE_YAW_AXIS  →  RIG_STAGE_PITCH_AXIS`

### Setting angles manually in Blender

1. Append/Link an export that contains the stage rig (e.g. `EXPORT_stage` or `EXPORT_joystick`).
2. In the Outliner, select the relevant rig empty:
   - Yaw: `RIG_STAGE_YAW_AXIS`
   - Pitch: `RIG_STAGE_PITCH_AXIS`
3. Rotate **around the empty’s local Z axis**.

**Do not assume the other two Euler angles are zero.**

In many rigs, the yaw/pitch empties are *pre-aligned* (their X/Y may be non-zero so that their local Z points along the real mechanical axis). In that case:
- You should **only add a delta rotation about local Z**, not overwrite the full rotation.

### Setting angles in Python (recommended pattern)

If you’re setting angles in a script, prefer “additive” rotation so you don’t destroy the alignment:

```python
import math
from mathutils import Quaternion

# Find the rig empties by name in the imported instance
yaw_obj   = bpy.data.objects["RIG_STAGE_YAW_AXIS"]
pitch_obj = bpy.data.objects["RIG_STAGE_PITCH_AXIS"]

# Store base alignment the first time (example: a custom property)
# This protects you from clobbering alignment rotations.
if "base_q" not in yaw_obj:
    yaw_obj["base_q"] = list(yaw_obj.rotation_quaternion)
if "base_q" not in pitch_obj:
    pitch_obj["base_q"] = list(pitch_obj.rotation_quaternion)

base_yaw_q   = Quaternion(yaw_obj["base_q"])
base_pitch_q = Quaternion(pitch_obj["base_q"])

yaw_deg = 15.0
pitch_deg = -10.0

q_yaw_delta   = Quaternion((0, 0, 1), math.radians(yaw_deg))
q_pitch_delta = Quaternion((0, 0, 1), math.radians(pitch_deg))

yaw_obj.rotation_quaternion   = base_yaw_q   @ q_yaw_delta
pitch_obj.rotation_quaternion = base_pitch_q @ q_pitch_delta
```

If you know the empties are already aligned with local Z and have zero X/Y, you can do a simpler:

```python
yaw_obj.rotation_euler.z += math.radians(yaw_deg)
pitch_obj.rotation_euler.z += math.radians(pitch_deg)
```

---

## 4) `pcb.blend` exports

The current PCB export set includes:

### A) Full PCB assembly
- **`EXPORT_pcb`**
  - `SRC_pcb`
  - `RIG_pcb`

**Main handle (move/rotate/scale the whole PCB):**
- `RIG_PCB_ROOT`

The full PCB rig also contains group handles:
- `RIG_PCB_G_PITCH_AXIS_CTRL`
- `RIG_PCB_G_YAW_AXIS_CTRL`
- `RIG_PCB_G_BRAKE`
- `RIG_PCB_G_TORQUE_SENSOR`
- `RIG_PCB_G_AUDIO`
- `RIG_PCB_G_MCU`

These are helpful if you want to “explode” PCB functional groups away from the board.

### B) PCB functional subset exports
- **`EXPORT_pcb_pitch_axis_ctrl`**
  - `SRC_pcb_pitch_axis_ctrl`
  - `RIG_pcb_pitch_axis_ctrl` (handle: `RIG_PCB_G_PITCH_AXIS_CTRL`)

- **`EXPORT_pcb_yaw_axis_ctrl`**
  - `SRC_pcb_yaw_axis_ctrl`
  - `RIG_pcb_yaw_axis_ctrl` (handle: `RIG_PCB_G_YAW_AXIS_CTRL`)

- **`EXPORT_pcb_brake`**
  - `SRC_pcb_brake`
  - `RIG_pcb_brake` (handle: `RIG_PCB_G_BRAKE`)

- **`EXPORT_pcb_torque_sensor`**
  - `SRC_pcb_torque_sensor`
  - `RIG_pcb_torque_sensor` (handle: `RIG_PCB_G_TORQUE_SENSOR`)

- **`EXPORT_pcb_audio`**
  - `SRC_pcb_audio`
  - `RIG_pcb_audio` (handle: `RIG_PCB_G_AUDIO`)

- **`EXPORT_pcb_mcu`**
  - `SRC_pcb_mcu`
  - `RIG_pcb_mcu` (handle: `RIG_PCB_G_MCU`)

---

## 5) Importing into your poster scene

### Option A — Append (simple, editable)

1. **File → Append**
2. Select the asset file (`joystick.blend` or `pcb.blend`)
3. Open the **Collection** folder
4. Choose an `EXPORT_*` collection
5. Click **Append**

Pros:
- You can directly rotate the rig empties per instance.

Cons:
- Asset updates don’t automatically propagate.

### Option B — Link (best for keeping assets “single source of truth”)

1. **File → Link** (same steps as Append)
2. After linking, use **Library Overrides** for per-instance rig edits:
   - Right-click the linked collection → *Make Library Override*

Pros:
- Updates to the source asset file can propagate.

Cons:
- You must use overrides to change yaw/pitch angles per instance.

---

## 6) Multiple instances (arrays) with different yaw/pitch

### Manual workflow (Append)
- Append `EXPORT_stage` once.
- Duplicate the imported stage collection/rig as many times as you want.
- For each instance:
  - Place it with `RIG_STAGE_ROOT` (or `RIG_JOYSTICK_ROOT` if you imported the full joystick).
  - Set yaw/pitch using `RIG_STAGE_YAW_AXIS` and `RIG_STAGE_PITCH_AXIS`.

### Script/manifest workflow (concept)

A simple per-instance schema that supports the poster layout:

```yaml
instances:
  - export: EXPORT_joystick
    location: [0.0, 0.0, 0.0]
    rot_z_deg: 25.0
    scale: 1.0
    stage:
      yaw_deg: 10.0
      pitch_deg: -5.0

  - export: EXPORT_stage
    location: [0.25, 0.00, 0.00]
    rot_z_deg: -15.0
    scale: 0.8
    stage:
      yaw_deg: 0.0
      pitch_deg: 30.0
```

Implementation idea:
1. Import the export collection.
2. Identify the instance’s stage rig empties.
3. Apply:
   - `RIG_STAGE_YAW_AXIS`: add yaw around local Z
   - `RIG_STAGE_PITCH_AXIS`: add pitch around local Z

---

## 7) Practical “do / don’t” rules

**Do:**
- Only transform `RIG_*` empties in a poster scene.
- Keep `EXPORT_*` collections as wrappers (no direct objects).
- For any functional unit you want to place repeatedly, create:
  - a `SRC_*` collection
  - a `RIG_*` collection with one clear handle empty
  - an `EXPORT_*` wrapper containing those two

**Don’t:**
- Move geometry objects into `EXPORT_*` directly.
- Animate/rotate objects inside `SRC_*` directly.
- Overwrite full rotations on yaw/pitch rig empties if they have alignment rotations.

---

## 8) Troubleshooting checklist

If something doesn’t rotate the way you expect:

1. Confirm you’re rotating **the rig empty**, not a mesh.
2. Confirm the mesh is parented (directly or indirectly) under the rig empty.
3. Confirm you’re rotating around the **correct axis** (local Z for yaw/pitch empties).
4. If the asset is linked, confirm you’re using a **Library Override**.

