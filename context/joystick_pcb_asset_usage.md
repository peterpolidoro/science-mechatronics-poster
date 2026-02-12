# Using joystick.blend and pcb.blend as reusable assets

This guide describes how the project’s Blender asset files are organized so you can reliably **append/link** whole assemblies *or* small “exploded view” subsets into a separate scene (your poster scene).

It also describes **how to set the 2‑axis stage angles** (Yaw + Pitch) after importing.

---

## 1) Naming conventions used in the asset .blend files

Each asset file follows the same pattern:

- **`EXPORT_*` collections**
  - *Entry points* you import into another .blend file.
  - These collections should contain **no objects directly** (only child collections).
  - Think of them as “public API” for the file.

- **`SRC_*` collections**
  - Contain the *actual geometry* (meshes) and any “source” empties that came from CAD imports.
  - Treat these as **read‑only**. Don’t animate or drive motion directly here.

- **`RIG_*` collections**
  - Contain **only rig empties** you are allowed to move/rotate.
  - The SRC objects are parented under these empties so rig transforms propagate correctly.

### Functional subset collections (exploded assemblies)

For exploded views you create additional group collections like:

- `SRC_joystick_pitch_axis_transducers` / `RIG_joystick_pitch_axis_transducers`
- `SRC_joystick_yaw_axis_transducers` / `RIG_joystick_yaw_axis_transducers`
- `SRC_joystick_brake` / `RIG_joystick_brake`
- `SRC_joystick_torque_sensor` / `RIG_joystick_torque_sensor`
- (PCB equivalents, e.g. pitch/yaw control electronics, brake electronics, etc.)

**Recommendation:** For every functional subset you want to place repeatedly, also add an `EXPORT_*` wrapper collection so you can append *one* thing instead of remembering “append SRC+RIG”.

Example wrapper pattern:

- `EXPORT_joystick_pitch_axis_transducers`
  - `SRC_joystick_pitch_axis_transducers`
  - `RIG_joystick_pitch_axis_transducers`

---

## 2) joystick.blend exports

### A) Full joystick assembly

Append/Link:

- `EXPORT_joystick`
  - `SRC_joystick`
  - `RIG_joystick`

Use when you want the **entire mechanical assembly**.

### B) 2‑axis stage only

Append/Link:

- `EXPORT_stage`
  - `SRC_stage`
  - `RIG_stage`

Use when you want **only the yaw/pitch stage** as a standalone object (for arrays, exploded views, etc).

---

## 3) The 2‑axis stage rig (Yaw + Pitch)

Inside the stage rig you will find these empties:

- `RIG_STAGE_ROOT`
  - Move/rotate this to position the entire stage assembly in the scene.
- `RIG_STAGE_YAW_AXIS`
  - Rotating this sets the **Yaw** angle.
- `RIG_STAGE_PITCH_AXIS`
  - Rotating this sets the **Pitch** angle.

They are parented like:

`RIG_STAGE_ROOT → RIG_STAGE_YAW_AXIS → RIG_STAGE_PITCH_AXIS`

### How to set angles manually in Blender

1. Import the stage (Append `EXPORT_stage`, or Append `EXPORT_joystick` if you want the full assembly).
2. In the Outliner, locate `RIG_STAGE_YAW_AXIS` and `RIG_STAGE_PITCH_AXIS`.
3. Set angles like this:
   - **Yaw angle**: change *only* the **Z rotation** of `RIG_STAGE_YAW_AXIS`.
   - **Pitch angle**: change *only* the **Z rotation** of `RIG_STAGE_PITCH_AXIS`.

Important:
- Those empties may have a **non‑zero “alignment” rotation** (e.g. X=180 or Y=-90) so their local Z axis matches the real mechanical axis.
- Do **not** zero out the other Euler components unless you re‑align the empty’s axes.

---

## 4) Importing into a poster scene (Append vs Link)

### Option A — Append (easy, fully editable)
Use **File → Append**, then choose:
- `<asset>.blend` → **Collection** → pick an `EXPORT_*` collection → **Append**

Pros:
- You can directly rotate rig empties to set yaw/pitch per instance.
- Easy for quick iteration.

Cons:
- If you update the asset file, you’ll need to re‑append or manage updates manually.

### Option B — Link (best for keeping assets “single source of truth”)
Use **File → Link** instead of Append.

Pros:
- Asset updates can propagate to the poster scene automatically.

Cons:
- To change yaw/pitch (or any internal rig transform), you usually need a **Library Override** in the poster scene.

---

## 5) Creating multiple stage instances (arrays)

### If you Append
- Append `EXPORT_stage` once.
- Duplicate the stage rig for multiple instances:
  - `Shift+D` (full duplicate) or `Alt+D` (linked duplicate of mesh data, separate object transforms)
- Each duplicate can have its own `RIG_STAGE_YAW_AXIS` / `RIG_STAGE_PITCH_AXIS` angles.

### If you Link
- Link `EXPORT_stage`.
- For each instance, create a Library Override (recommended workflow) so you can set the yaw/pitch angles per instance.

---

## 6) Example manifest idea (for scripted importing)

If you have a Python importer that reads a manifest, a simple **recommended** per‑instance schema is:

```yaml
instances:
  - asset_blend: "assets/compiled/blend/joystick.blend"
    export_collection: "EXPORT_stage"
    location: [0.0, 0.0, 0.0]
    rotation_z_deg: 25.0
    scale: 1.0
    stage_angles_deg:
      yaw: 10.0
      pitch: -5.0

  - asset_blend: "assets/compiled/blend/joystick.blend"
    export_collection: "EXPORT_stage"
    location: [0.20, 0.00, 0.00]
    rotation_z_deg: -15.0
    scale: 0.8
    stage_angles_deg:
      yaw: 0.0
      pitch: 30.0
```

Importer behavior:
1. Append/Link the `export_collection`.
2. Find `RIG_STAGE_YAW_AXIS` and `RIG_STAGE_PITCH_AXIS` inside the imported hierarchy.
3. Apply:
   - `RIG_STAGE_YAW_AXIS.rotation_euler.z = radians(yaw_deg)`
   - `RIG_STAGE_PITCH_AXIS.rotation_euler.z = radians(pitch_deg)`
   while preserving the empties’ alignment rotations.

---

## 7) pcb.blend exports (pattern)

pcb.blend should follow the same pattern:

- `EXPORT_pcb` (full board assembly)
  - `SRC_pcb`
  - `RIG_pcb`

Plus optional functional subset exports, e.g.:
- `EXPORT_pcb_pitch_axis_ctrl`
- `EXPORT_pcb_yaw_axis_ctrl`
- `EXPORT_pcb_brake`
- `EXPORT_pcb_torque_sensor`
- `EXPORT_pcb_audio`
- `EXPORT_pcb_microcontroller`

Each subset export should wrap:
- the subset `SRC_*` collection
- the subset `RIG_*` collection (the “handle” empty)

This makes it easy to place “electronics islands” around the mechanical assembly in exploded views.

---

## 8) Practical tips for exploded layouts

- Use **empties as handles** for each functional unit:
  - Place the empty at the “center of meaning” for the unit (connector, mounting holes, etc.)
  - When you duplicate instances, move/rotate only the handle empty.
- Keep the “documentation items” (schematic image planes, firmware screenshots, labels) inside the same export wrapper as the physical components.
- For clean poster composition:
  - Put each imported unit into its own top-level collection in the poster scene (e.g. `SCENE_ASSET_01_STAGE_A`, `SCENE_ASSET_02_PCB_PITCH_CTRL`, …).
  - Use consistent naming so scripts can find/update units later.

---

## 9) Troubleshooting checklist

If something does not rotate correctly:
- Verify the objects that should move are parented under the correct rig empty.
- Verify you are rotating the **rig empty**, not a mesh.
- Verify you only change the intended Euler component (usually Z).
- If you linked the asset: verify you created a **Library Override** before editing rig transforms.

