SHELL := bash
.ONESHELL:
.RECIPEPREFIX := >
.DEFAULT_GOAL := help

# --------------------------
# User-configurable knobs
# --------------------------
BLENDER ?= $(HOME)/bin/blender-5.0.1-linux-x64/blender
MANIFEST ?= poster/manifest.json
OUT_DIR ?= out

PREVIEW_PPI ?= 150
FINAL_PPI ?= 300

# VRML(.wrl) -> GLB conversion defaults (only used if you run `make convert-wrl`)
WRL_IN ?= assets/src/wrl
GLB_OUT ?= assets/compiled/glb
# If your WRL coordinates are in millimeters, use 0.001 to convert mm -> meters for GLB export.
WRL_SCALE ?= 0.001

# --------------------------
# Project-local Blender dirs
# --------------------------
export BLENDER_USER_CONFIG := $(CURDIR)/.blender/user_config
export BLENDER_USER_SCRIPTS := $(CURDIR)/.blender/user_scripts
export BLENDER_USER_EXTENSIONS := $(CURDIR)/.blender/user_extensions

.PHONY: help
help:
>@cat <<'EOF'
>science-mechatronics-poster (Makefile)
>
>Core:
>  make open              Open Blender UI and apply poster/manifest.json
>  make open-clean        Same as open, but uses --factory-startup
>  make render-preview    Headless render at PREVIEW_PPI -> out/poster_preview_<ppi>ppi.png
>  make render-final      Headless render at FINAL_PPI   -> out/poster_final_<ppi>ppi.png
>
>Utilities:
>  make render PPI=200 OUT=out/poster_200ppi.png
>  make convert-wrl       Batch convert assets/src/wrl/*.wrl -> assets/compiled/glb/*.glb
>
>Guix helpers:
>  make freecad           Run FreeCAD in a guix shell
>  make kicad             Run KiCad in a guix shell
>  make gimp              Run GIMP in a guix shell
>
>Variables you can override:
>  BLENDER=/path/to/blender
>  MANIFEST=poster/manifest.json
>  PREVIEW_PPI=150 FINAL_PPI=300
>  WRL_IN=... GLB_OUT=... WRL_SCALE=0.001
>EOF

.PHONY: dirs
dirs:
>mkdir -p "$(OUT_DIR)" \
>  "$(BLENDER_USER_CONFIG)" \
>  "$(BLENDER_USER_SCRIPTS)" \
>  "$(BLENDER_USER_EXTENSIONS)"

# --------------------------
# Blender UI
# --------------------------
.PHONY: open
open: dirs
>"$(BLENDER)" --python "poster/open.py" -- "$(MANIFEST)"

.PHONY: open-clean
open-clean: dirs
>"$(BLENDER)" --factory-startup --python "poster/open.py" -- "$(MANIFEST)"

# --------------------------
# Headless renders
# --------------------------
.PHONY: render-preview
render-preview: dirs
>"$(BLENDER)" -b --factory-startup --python "poster/render.py" -- \
>  "$(MANIFEST)" \
>  --output "$(OUT_DIR)/poster_preview_$(PREVIEW_PPI)ppi.png" \
>  --ppi "$(PREVIEW_PPI)"

.PHONY: render-final
render-final: dirs
>"$(BLENDER)" -b --factory-startup --python "poster/render.py" -- \
>  "$(MANIFEST)" \
>  --output "$(OUT_DIR)/poster_final_$(FINAL_PPI)ppi.png" \
>  --ppi "$(FINAL_PPI)"

.PHONY: render
render: dirs
>: $${PPI:?Usage: make render PPI=200 OUT=out/poster_200ppi.png}
>: $${OUT:?Usage: make render PPI=200 OUT=out/poster_200ppi.png}
>"$(BLENDER)" -b --factory-startup --python "poster/render.py" -- \
>  "$(MANIFEST)" \
>  --output "$(OUT)" \
>  --ppi "$(PPI)"

.PHONY: clean
clean:
>rm -rf "$(OUT_DIR)"/*

# --------------------------
# Asset conversion
# --------------------------
.PHONY: convert-wrl
convert-wrl: dirs
>mkdir -p "$(GLB_OUT)"
>"$(BLENDER)" -b --factory-startup --python "tools/convert_wrl_to_glb.py" -- \
>  "$(WRL_IN)" "$(GLB_OUT)" "$(WRL_SCALE)"

# --------------------------
# Guix helper targets
# --------------------------
GUIX ?= guix
GUIX_MANIFEST ?= guix/manifest.scm

.PHONY: freecad
freecad:
>"$(GUIX)" shell -m "$(GUIX_MANIFEST)" -- freecad

.PHONY: kicad
kicad:
>"$(GUIX)" shell -m "$(GUIX_MANIFEST)" -- kicad

.PHONY: gimp
gimp:
>"$(GUIX)" shell -m "$(GUIX_MANIFEST)" -- gimp
