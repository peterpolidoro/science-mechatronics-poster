# Science Mechatronics Poster (Blender) — Project Context

**Purpose:** A **48×48 inch** (1219.2×1219.2 mm) poster rendered from a Blender scene that looks like an **exploded CAD assembly** (perspective camera, not orthographic). The scene is built **reproducibly from a declarative manifest** and rendered via Makefile targets.

**Current date:** 2026-02-08 (America/New_York)

---

## High-level workflow

1. **Assets live in the repo** (`assets/…`).
2. The **poster scene is generated from `poster/manifest.json`** using `poster/blendlib.py`.
3. `make open` runs Blender with `poster/open.py` to open an interactive scene from the manifest.
4. `make render-preview` / `make render-final` runs Blender headless with `poster/render.py` to render a reproducible image.

**Key principle:** don’t do manual edits inside the poster scene file; instead:
- edit source assets (now primarily `.blend` assets under `assets/compiled/blend/`), or
- change the manifest and re-run `make open` / `make render`.

---

## Units & coordinate conventions

- The project uses **millimeters**:
  - “1 Blender unit = 1 mm” convention.
  - In Blender terms this is commonly represented by **Unit Scale = 0.001** (meters per BU).
- Poster layout positioning uses **poster millimeters** as well:
  - Overlay image planes are placed in “POSTER” space relative to the camera plane using `poster_xy_mm` and `size_mm`.

---

## Repository structure (important paths)

Typical structure used in this project:

```
poster/
  manifest.json          # declarative scene description
  blendlib.py            # scene-building library used by open.py + render.py
  open.py                # opens scene from manifest in UI mode
  render.py              # headless render entrypoint; supports overrides

assets/
  src/                   # ORIGINAL upstream assets (do not overwrite)
    glb/                 # original glb assemblies
    wrl/                 # original wrl assemblies (optional)
    blend/               # DEV assets (.blend) that can link to materials library
  compiled/
    blend/               # COMPILED poster-ready assets (.blend only)
  images/
    title.png            # header/title image plane at top of poster
    figure.png           # overlay figure (bottom-left) tilted toward origin
    paper.png            # overlay paper (upper-right) tilted toward origin

assets/library/
  materials/
    materials.blend            # shared material library (source of truth)
    materials_catalog.json     # auto-generated catalog (text, commit-friendly)
    textures/                  # optional; texture sources for library materials

tools/
  materials/
    material_recipes.py   # text definitions of materials
    build_library.py      # builds/updates materials.blend + catalog JSON
    sync_to_asset.py      # link/bake workflow for assets
```

Blender user config is kept project-local (created by Makefile) to improve reproducibility:

```
.blender/user_config
.blender/user_scripts
.blender/user_extensions
```

---

## Makefile targets (core)

The Makefile supports:

### Open / interactive
- `make open`
- `make open-clean` (uses `--factory-startup`)

### Renders
- `make render-preview` (Cycles, PPI = `PREVIEW_PPI`)
- `make render-preview-fast` (Eevee Next, very fast; for layout/testing)
- `make render-preview-cycles-fast` (Cycles but **16 samples + no denoise**)
- `make render-final` (Cycles, PPI = `FINAL_PPI`)
- `make render PPI=200 OUT=out/poster_200ppi.png`

### Material library hybrid workflow (link while developing, bake for compiled)
- `make materials-build`
- `make materials-link`
- `make materials-bake`
- `make materials-link-then-bake`

All headless renders are run with `--factory-startup` for reproducibility.

---

## GPU rendering (AMD HIP) — single GPU only

System context:
- Debian Trixie
- AMD GPU: **Radeon RX 7600** + integrated “AMD Radeon Graphics”
- Blender sees HIP after ROCm/HIP runtime installation.

**Requirement:** Use only the RX 7600 (not both GPUs).

### How this is implemented
- `poster/manifest.json` contains Cycles settings including:
  - `compute_device_type: "HIP"`
  - `device: "GPU"`
  - `use_all_gpus: false`
  - `preferred_devices: ["AMD Radeon RX 7600"]`
  - `use_cpu: false`

- `poster/blendlib.py` contains a function like `configure_cycles_devices(cfg)` which is called whenever Cycles is active. This is necessary because `--factory-startup` resets Preferences each render.

### How to verify during render
`poster/render.py` prints:
- `scene.cycles.device`
- `prefs.compute_device_type`
- enabled devices list (should show only `HIP:AMD Radeon RX 7600`)

CPU can still spike due to BVH building/scene prep; GPU usage must be checked via the “enabled devices” print or using `amd-smi metric` externally.

---

## Manifest schema (key parts)

`poster/manifest.json` includes sections like:

- **poster**
  - width/height in mm, PPI defaults, camera plane distance, etc.
- **render / cycles / eevee / color management**
  - engine preference list
  - cycles samples/denoise
  - background/film settings
- **camera**
  - perspective camera
  - `location_mm`, `target_mm`, lens, etc.
- **lights**
  - studio-ish multi-area-light setup (key/fill/rim/top), energies in Watts
- **objects** (list)
  - imported assets
  - overlay images (image planes)
  - optional text, arrows, etc.

### .blend assets (new primary asset format)
Objects can use:

```json
{
  "name": "joystick",
  "kind": "import_blend",
  "collection": "WORLD",
  "filepath": "../assets/compiled/blend/joystick.blend",
  "blend_collection": "EXPORT_joystick",
  "link": true,
  "location_mm": [x, y, z],
  "rotation_deg": [rx, ry, rz],
  "scale": [sx, sy, sz],
  "import_scale": 1.0
}
```

**Behavior in `blendlib.py`:**
- Creates a root empty named `<name>` and puts it in `HELPERS` (hidden in renders).
- Creates `ASSET_<name>` collection under the target parent (usually `WORLD`).
- Loads a collection from the external `.blend` and creates an instance empty (`INST_<name>`) that instances the loaded collection.
- Applies location/rotation/scale to the root empty so the whole assembly transforms together.

**Important:** To make imports predictable, compiled asset `.blend` files should contain a stable collection name like:
- `EXPORT_joystick`, `EXPORT_pcb`, etc.

The loader uses fallbacks if `blend_collection` doesn’t exist:
- tries `EXPORT_<name>`, `<name>`, `Collection`, and finally any available collection (prefers `EXPORT_*`).

---

## Overlay image planes (title / figure / paper)

Overlay images are implemented as `kind: "image_plane"`.

They can be placed in **POSTER space** (camera-relative) so you specify their position in poster mm:

Key fields:
- `space: "POSTER"`
- `poster_xy_mm: [x_mm, y_mm]`  (poster plane coords)
- `size_mm: [w_mm, h_mm]`
- `z_mm: ...` (depth relative to reference poster plane)
- `screen_lock: true` (keep on-poster placement/size fixed even when changing `z_mm`)
- `aim_target_mm: [0,0,0]` (world origin)
- `aim_target_name: "EMPTY_WorldOrigin"`
- `aim_track_axis: "TRACK_NEGATIVE_Z"`
- `aim_up_axis: "UP_Y"`

### Verified orientation requirement
Goal: plane’s perpendicular ray through image center intersects **world [0,0,0]**.

A verification script was run in Blender and produced:

- `figure: angle_deg=0.000000, line_distance_mm=0.000002`
- `paper:  angle_deg=0.000000, line_distance_mm=0.000004`

So the Track-To aiming is correct.

### Make the tilt more dramatic (while keeping readable)
Because `screen_lock: true` + very large `z_mm` makes tilt visually subtle, the recommended knob is:
- **decrease** `z_mm` (moves plane farther from camera, increasing required tilt)
- adjust `size_mm` slightly if readability suffers

---

## Material library (hybrid workflow)

### Goal
- Develop materials centrally in `assets/library/materials/materials.blend`.
- During development, dev assets **link** materials from the library so updates propagate.
- For poster-ready compiled assets, **bake** linked materials to local and **pack resources**.

### Files
- `tools/materials/material_recipes.py`: material specs (text)
- `tools/materials/build_library.py`: builds `materials.blend` and writes `materials_catalog.json`
- `tools/materials/sync_to_asset.py`: link/bake/link_then_bake for asset .blend files

### Commands (from repo root)

Build/update library:
```bash
make materials-build
```

Link into a dev asset:
```bash
make materials-link DEV_ASSET=assets/src/blend/joystick_dev.blend
```

Bake into compiled:
```bash
make materials-bake DEV_ASSET=assets/src/blend/joystick_dev.blend COMPILED_ASSET=assets/compiled/blend/joystick.blend
```

Or one-step:
```bash
make materials-link-then-bake DEV_ASSET=... COMPILED_ASSET=...
```

---

## Debugging notes

### Where `print()` output goes
- If Blender is launched from terminal (`make open`, `make render-*`), `print()` output appears in that **terminal**.
- Blender UI may also show logs in “System Console” (platform-dependent).

---

## What to upload to a NEW chat to continue development

Upload these files (text) so the new chat can reason about the project accurately:

### Essential (poster pipeline)
1. `poster/manifest.json`
2. `poster/blendlib.py`
3. `poster/render.py`
4. `poster/open.py`
5. `Makefile`

### If working on materials
6. `tools/materials/material_recipes.py`
7. `tools/materials/build_library.py`
8. `tools/materials/sync_to_asset.py`
9. `assets/library/materials/materials_catalog.json`

### If debugging layout/composition
10. The latest rendered preview PNG (e.g. `out/poster_preview_*.png`)
11. Any overlay images involved (`assets/images/title.png`, `figure.png`, `paper.png`)

(You typically do **not** need to upload binary `.blend` assets unless we’re debugging import/collection naming issues.)

---

## Next likely steps

- Iterate `z_mm` for `figure`/`paper` to achieve desired dramatic tilt.
- Improve joystick/pcb materials via the library, then bake to compiled assets.
- Add exploded parts via additional instances of the same `.blend` collections and/or split export collections in asset files.
