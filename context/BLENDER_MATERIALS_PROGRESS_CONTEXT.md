# Blender 5 Materials Progress Context (for continuing in a new chat)

Date: 2026-02-08  
Blender version: **Blender 5** (user)  
Primary goal: **Make a GLB-imported assembly look realistic in Blender by upgrading materials**, focusing first on a **stepper motor**.

---

## 1) Current workflow decision

- You imported the original assembly as a **.glb** into Blender and saved it as a **.blend**.
- You **will not** roundtrip objects by exporting/importing again.
- You want to **create reusable materials** (in a separate “library” workflow), then **import/link** those materials into your assembly `.blend` and assign them to objects/faces.

---

## 2) Project material-library system (repo/tooling)

This project is set up as a **material library → dev asset (linked) → compiled asset (baked)** workflow.

### Key files and paths (as used in our discussion)

- Material recipes:  
  `tools/materials/material_recipes.py`  
  - Contains a `MATERIAL_SPECS` dictionary (source-of-truth for materials).

- Build the materials library `.blend` + a catalog JSON:  
  `tools/materials/build_library.py`  
  Outputs:
  - `assets/library/materials/materials.blend`
  - `assets/library/materials/materials_catalog.json`

- Sync materials into an asset `.blend` (usually the **dev** file) by linking:  
  `tools/materials/sync_to_asset.py`

- Dev vs compiled:
  - Dev (editable, linked): `assets/src/blend/joystick_dev.blend`
  - Compiled (output): `assets/compiled/blend/joystick.blend`

### Important behavior
- **New** materials added to `MATERIAL_SPECS` require re-running:
  1) `build_library.py` (to update `materials.blend`)
  2) `sync_to_asset.py --mode link` (to bring new datablocks into the dev asset)
- If you open the **compiled** file (`joystick.blend`) and don’t see new materials:
  - You likely linked into `joystick_dev.blend`, not the compiled file.
  - Or you baked with `--bake-used-only` and the new materials weren’t assigned anywhere yet.

---

## 3) Commands we used

### A) Rebuild / update the material library
Run from repo root:

```bash
blender -b --factory-startup --python tools/materials/build_library.py --   --library assets/library/materials/materials.blend   --catalog assets/library/materials/materials_catalog.json
```

### B) Link materials into the dev asset blend
Run from repo root:

```bash
blender -b --factory-startup --python tools/materials/sync_to_asset.py --   --mode link   --asset assets/src/blend/joystick_dev.blend   --library assets/library/materials/materials.blend   --materials "MAT_*"
```

Notes:
- The script links materials matching patterns (we used `MAT_*`).
- Ensure new materials follow the naming convention `MAT_<Category>_<Name>` so they match.

---

## 4) How to verify materials are present (Blender GUI + script)

### A) GUI quick check
Open **`assets/src/blend/joystick_dev.blend`** and:
1. Select any mesh object.
2. Go to **Material Properties**.
3. Click the material dropdown and type `MAT_` to search.

If the materials exist in the file, they appear even if unassigned.

### B) Definitive script check (prints MAT_* materials)
In Blender → Scripting tab → run:

```python
import bpy

print("Current file:", bpy.data.filepath)

hits = []
for m in bpy.data.materials:
    if m.name.startswith("MAT_"):
        hits.append((m.name, "LINKED" if m.library else "LOCAL", m.users))

for row in sorted(hits):
    print(row)

print("Count MAT_*:", len(hits))
```

Interpretation:
- `LINKED` means the material is coming from `materials.blend` (expected in dev).
- `m.users` tells you whether it is assigned anywhere yet.

### C) GUI fallback (manual import)
If scripts fail or you want a quick manual test:
- **File → Append** (makes local copies)
- or **File → Link** (keeps linked)
- Choose `assets/library/materials/materials.blend` → `Material/` → pick materials.

---

## 5) Multi-material objects (single mesh) – no need to split

You **do not** need to split a mesh into multiple objects to have multiple materials.

Standard method:
1. Select object → **Material Properties**.
2. Add multiple **Material Slots** (`+`).
3. Go to **Edit Mode**.
4. Select faces for a part.
5. Pick the correct slot and click **Assign**.

Useful selection shortcuts:
- Hover and press **L** (Select Linked under mouse) for mesh “islands.”
- Use the material slot buttons **Select / Deselect** to validate assignments.

Optional: after assigning by face/material, you can split later if desired:
- Edit Mode → `P` → **Separate → By Material**.

---

## 6) Recommended object prep for realism + easier material work

Even great shaders look fake on CAD-like meshes with razor-sharp edges and poor normals.

Recommended *non-destructive* prep:
- **Shade Smooth**
- **Shade Auto Smooth** (Blender 5 uses Smooth By Angle modifier style)
- Add a **Bevel** modifier (tiny bevels for real edge breaks)
- Add a **Weighted Normal** modifier after bevel

We shared a batch “prep selected objects” script that:
- Shade Smooth
- Shade Auto Smooth
- Adds Bevel + Weighted Normal if missing

(Use it on selected motor parts or other hero objects.)

---

## 7) Stepper motor material set and where it goes

Reference: stepper motor photo shows **matte black body**, **silver end bells/caps**, **steel shaft**, and often a **plastic connector**.

### Recommended mapping (typical)
- Motor body / laminated stack / black housing → **black paint / powder coat**
- End bells / silver caps / front plate → **cast aluminum**
- Machined ring/face features (if any) → **machined aluminum**
- Shaft → **polished steel** (already exists in project as `MAT_Steel_Polished`, if present)
- Screws → **black oxide steel**
- Connector housing → **gray plastic**

Important note:
- We did **not** inspect your actual assembly geometry/object names; this mapping is the intended real-world assignment.

---

## 8) Materials created so far (added to `MATERIAL_SPECS`)

All values are **starting points** designed to look plausible in Blender/Cycles and be compatible with the project recipe system (Principled parameters supported by the helper).

### Stepper motor / hardware materials

**MAT_Paint_Black_PowderCoat**  
- base_color_rgba: `[0.02, 0.02, 0.02, 1.0]`
- metallic: `0.0`
- roughness: `0.60`
- specular: `0.50`
- ior: `1.45`
- coat: `0.08`
- coat_roughness: `0.35`

**MAT_Aluminum_Cast_Matte**  
- base_color_rgba: `[0.78, 0.78, 0.80, 1.0]`
- metallic: `1.0`
- roughness: `0.55`
- specular: `0.50`
- ior: `1.45`

**MAT_Aluminum_Machined**  
- base_color_rgba: `[0.83, 0.83, 0.85, 1.0]`
- metallic: `1.0`
- roughness: `0.28`
- specular: `0.50`
- ior: `1.45`

**MAT_Steel_Black_Oxide**  
- base_color_rgba: `[0.06, 0.06, 0.06, 1.0]`
- metallic: `1.0`
- roughness: `0.35`
- specular: `0.50`
- ior: `1.45`

**MAT_Plastic_Grey**  
- base_color_rgba: `[0.65, 0.65, 0.65, 1.0]`
- metallic: `0.0`
- roughness: `0.45`
- specular: `0.50`
- ior: `1.45`
- coat: `0.05`
- coat_roughness: `0.30`

### Additional requested materials

**MAT_Gold_Polished**  
- base_color_rgba: `[1.00, 0.77, 0.34, 1.0]`
- metallic: `1.0`
- roughness: `0.14`
- specular: `0.50`
- ior: `1.45`

**MAT_Plastic_Green**  
- base_color_rgba: `[0.06, 0.45, 0.12, 1.0]`
- metallic: `0.0`
- roughness: `0.42`
- specular: `0.50`
- ior: `1.45`
- coat: `0.08`
- coat_roughness: `0.25`

**MAT_Plastic_Red**  
- base_color_rgba: `[0.65, 0.06, 0.06, 1.0]`
- metallic: `0.0`
- roughness: `0.40`
- specular: `0.50`
- ior: `1.45`
- coat: `0.10`
- coat_roughness: `0.22`

**MAT_Rubber_Blue**  
- base_color_rgba: `[0.05, 0.12, 0.55, 1.0]`
- metallic: `0.0`
- roughness: `0.82`
- specular: `0.20`
- ior: `1.45`
- coat: `0.00`

Existing project materials noted during the work (already present in the recipes file):
- `MAT_Paint_Red_Gloss` (already existed; we added `MAT_Plastic_Red` as a less “car-paint” alternative)
- `MAT_Rubber_Black` (used as baseline for blue rubber)
- `MAT_Steel_Polished` (recommended for shafts)

---

## 9) Practical “next steps” inside your assembly blend

1. Open **`joystick_dev.blend`** (dev file).
2. Confirm the new materials exist using GUI search `MAT_...` or the script.
3. For each “hero” object (stepper motor and nearby parts):
   - Prep shading/normals (smooth + auto smooth + bevel + weighted normal).
4. Assign materials:
   - If separate objects: assign per object.
   - If single mesh: assign per-face with material slots.
5. Only when ready:
   - Bake/compile into `assets/compiled/blend/joystick.blend` (if your poster pipeline expects the compiled file).

---

## 10) Notes / constraints carried forward

- We have not directly inspected the assembly `.blend` geometry in this chat; assignments are recommended-by-function and require you to identify the motor parts (object names or face regions).
- If the compiled file doesn’t show new materials, verify:
  - You updated the library (build step succeeded),
  - You linked into **dev**,
  - You’re opening the right file,
  - And (if baking) the materials are assigned or bake isn’t filtering unused materials.

