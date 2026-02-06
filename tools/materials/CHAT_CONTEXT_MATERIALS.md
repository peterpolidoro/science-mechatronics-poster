# Science Mechatronics Poster — Material Library Context

This repository builds a **Blender-rendered poster** from a declarative `poster/manifest.json`.
We work in **millimeters** (`1 Blender Unit = 1 mm`, `scale_length = 0.001`).

## Goals

- Maintain a shared **material library** (`materials.blend`) that is the *source of truth* for reusable materials.
- During material development, **assets link** to the library so updates propagate automatically.
- For poster-ready “compiled” assets, we **bake** linked materials to local and **pack** resources so compiled assets are self-contained.

## Repository locations

### Material library (source of truth)

- Library blend:
  - `assets/library/materials/materials.blend`
- Material definitions (editable, text):
  - `tools/materials/material_recipes.py`
- Catalog JSON (auto-generated; commit-friendly, useful for prompts):
  - `assets/library/materials/materials_catalog.json`

### Asset files (hybrid workflow)

Recommended pattern:

- Dev asset (editable, *linked* to the material library):
  - `assets/src/blend/<asset>_dev.blend`
- Compiled asset (poster uses this; materials are *baked local* + packed):
  - `assets/compiled/blend/<asset>.blend`

Your poster manifest should reference assets under `assets/compiled/blend`.

## Commands (copy/paste)

Run these from the repo root.

### Build/update the material library

```bash
blender -b --factory-startup --python tools/materials/build_library.py -- \
  --library assets/library/materials/materials.blend \
  --catalog assets/library/materials/materials_catalog.json
```

Edit `tools/materials/material_recipes.py` to add more materials, then re-run this.

### Link library materials into a dev asset

This brings new materials into the dev asset while keeping them linked (live-updating).

```bash
blender -b --factory-startup --python tools/materials/sync_to_asset.py -- \
  --mode link \
  --asset assets/src/blend/joystick_dev.blend \
  --library assets/library/materials/materials.blend \
  --materials "MAT_*"
```

### Bake dev asset into a compiled asset

This makes linked materials (and common dependencies) local, and packs resources so the compiled `.blend` is self-contained.

```bash
blender -b --factory-startup --python tools/materials/sync_to_asset.py -- \
  --mode bake \
  --asset assets/src/blend/joystick_dev.blend \
  --out assets/compiled/blend/joystick.blend \
  --pack
```

### Convenience: link then bake in one go

```bash
blender -b --factory-startup --python tools/materials/sync_to_asset.py -- \
  --mode link_then_bake \
  --asset assets/src/blend/joystick_dev.blend \
  --out assets/compiled/blend/joystick.blend \
  --library assets/library/materials/materials.blend \
  --materials "MAT_*" \
  --pack
```

## Material authoring rules

- Keep names stable and prefixed:
  - `MAT_Plastic_Black`, `MAT_Aluminum_Brushed`, …
- Prefer physically plausible ranges:
  - Roughness: ~0.05–0.9
  - Metallic: 0 or 1 in most cases
- If you add textures later:
  - Store them under `assets/library/materials/textures/`
  - Keep file paths relative (the scripts attempt to make paths relative)

## What to upload to a new ChatGPT chat to create new materials

Upload these files (text-based):

1. `CHAT_CONTEXT_MATERIALS.md` (this file)
2. `tools/materials/material_recipes.py` (where materials are defined)
3. `assets/library/materials/materials_catalog.json` (current material list/specs)
4. `tools/materials/build_library.py` (how the library is built)
5. `tools/materials/sync_to_asset.py` (how linking/baking works)

Optional but helpful:
- a screenshot/render showing the look you want (reference)
- an object/part naming list for an asset if you want automated assignment rules

## Notes

- In LINK mode, **existing** linked materials update automatically when you open the dev asset/poster.
  Adding **new** materials to the library requires running LINK again to bring the new datablocks into the dev asset.
- In BAKE mode, the compiled asset should have **no remaining library references** (the script prints a report).
