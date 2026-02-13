SHELL := bash
.ONESHELL:
.DEFAULT_GOAL := help

# --------------------------
# User-configurable knobs
# --------------------------
BLENDER ?= $(HOME)/bin/blender-5.0.1-linux-x64/blender
MANIFEST ?= poster/manifest.json
OUT_DIR ?= out

PREVIEW_PPI ?= 150
FINAL_PPI ?= 300

# Fast preview (Eevee)
PREVIEW_FAST_PPI ?= 75
PREVIEW_FAST_ENGINE ?= BLENDER_EEVEE_NEXT
PREVIEW_FAST_EEVEE_SAMPLES ?= 16

# Fast preview (Cycles)
PREVIEW_CYCLES_FAST_PPI ?= $(PREVIEW_PPI)
PREVIEW_CYCLES_FAST_SAMPLES ?= 16

# Optional debugging flags for Blender (examples: --debug-cycles, --debug-gpu, --debug-all)
BLENDER_DEBUG ?=

# Optional: limit CPU threads Blender can use (0 = all, 1..N = limit)
THREADS ?=

# --------------------------
# Material library workflow (hybrid link->bake)
# --------------------------
MATERIAL_BUILD_SCRIPT ?= tools/materials/build_library.py
MATERIAL_SYNC_SCRIPT ?= tools/materials/sync_to_asset.py

MATERIAL_LIBRARY ?= assets/library/materials/materials.blend
MATERIAL_CATALOG ?= assets/library/materials/materials_catalog.json
MATERIAL_RECIPES ?= tools/materials/material_recipes.py

# Which materials to link from the library into a dev asset (glob pattern)
MATERIAL_GLOB ?= MAT_*

# Dev asset (linked materials) and compiled asset (baked + packed)
DEV_ASSET ?= assets/src/blend/joystick_dev.blend
COMPILED_ASSET ?= assets/compiled/blend/joystick.blend

# Whether to pack external resources when baking (1=yes, 0=no)
MATERIAL_PACK ?= 1

# --------------------------
# Project-local Blender dirs
# --------------------------
export BLENDER_USER_CONFIG := $(CURDIR)/.blender/user_config
export BLENDER_USER_SCRIPTS := $(CURDIR)/.blender/user_scripts
export BLENDER_USER_EXTENSIONS := $(CURDIR)/.blender/user_extensions

.PHONY: help
help:
	@echo "science-mechatronics-poster"
	@echo ""
	@echo "Core:"
	@echo "  make open                        Open Blender UI and apply $(MANIFEST)"
	@echo "  make open-clean                  Same as open, but uses --factory-startup"
	@echo ""
	@echo "Renders:"
	@echo "  make render-preview              Headless Cycles render at PREVIEW_PPI ($(PREVIEW_PPI))"
	@echo "  make render-preview-cycles-fast  Cycles preview (samples=$(PREVIEW_CYCLES_FAST_SAMPLES), no denoise)"
	@echo "  make render-preview-fast         Headless Eevee render at PREVIEW_FAST_PPI ($(PREVIEW_FAST_PPI))"
	@echo "  make render-final                Headless Cycles render at FINAL_PPI ($(FINAL_PPI))"
	@echo ""
	@echo "Materials (hybrid link->bake):"
	@echo "  make materials-build             Build/update $(MATERIAL_LIBRARY) from $(MATERIAL_RECIPES)"
	@echo "  make materials-link              Link materials into DEV_ASSET ($(DEV_ASSET))"
	@echo "  make materials-bake              Bake DEV_ASSET -> COMPILED_ASSET (pack=$(MATERIAL_PACK))"
	@echo "  make materials-link-then-bake    Link then bake in one step"
	@echo ""
	@echo "Generic:"
	@echo "  make render PPI=200 OUT=out/poster_200ppi.png"
	@echo ""
	@echo "Debug:"
	@echo "  make render-preview-debug        Same as render-preview but adds --debug-cycles"
	@echo ""
	@echo "Variables you can override:"
	@echo "  BLENDER=/path/to/blender"
	@echo "  THREADS=8"
	@echo "  PREVIEW_PPI=150 FINAL_PPI=300"
	@echo "  PREVIEW_FAST_ENGINE=BLENDER_EEVEE_NEXT PREVIEW_FAST_EEVEE_SAMPLES=16"
	@echo "  PREVIEW_CYCLES_FAST_SAMPLES=16"
	@echo "  MATERIAL_GLOB=MAT_*"
	@echo "  DEV_ASSET=assets/src/blend/joystick_dev.blend"
	@echo "  COMPILED_ASSET=assets/compiled/blend/joystick.blend"

.PHONY: dirs
dirs:
	mkdir -p "$(OUT_DIR)" \
	  "$(BLENDER_USER_CONFIG)" \
	  "$(BLENDER_USER_SCRIPTS)" \
	  "$(BLENDER_USER_EXTENSIONS)"

# --------------------------
# Blender UI
# --------------------------
.PHONY: open
open: dirs
	"$(BLENDER)" $(BLENDER_DEBUG) --python "poster/open.py" -- "$(MANIFEST)"

.PHONY: open-clean
open-clean: dirs
	"$(BLENDER)" --factory-startup $(BLENDER_DEBUG) --python "poster/open.py" -- "$(MANIFEST)"

# --------------------------
# Headless renders
# --------------------------
define BLENDER_BG
"$(BLENDER)" -b --factory-startup $(BLENDER_DEBUG) $(if $(THREADS),-t $(THREADS),)
endef

.PHONY: render-preview
render-preview: dirs
	$(BLENDER_BG) --python "poster/render.py" -- \
	  "$(MANIFEST)" \
	  --output "$(OUT_DIR)/poster_preview_$(PREVIEW_PPI)ppi.png" \
	  --ppi "$(PREVIEW_PPI)"

.PHONY: render-preview-cycles-fast
render-preview-cycles-fast: dirs
	$(BLENDER_BG) --python "poster/render.py" -- \
	  "$(MANIFEST)" \
	  --output "$(OUT_DIR)/poster_preview_cycles_fast_$(PREVIEW_CYCLES_FAST_PPI)ppi.png" \
	  --ppi "$(PREVIEW_CYCLES_FAST_PPI)" \
	  --engine "CYCLES" \
	  --cycles-samples "$(PREVIEW_CYCLES_FAST_SAMPLES)" \
	  --no-denoise

.PHONY: render-preview-fast
render-preview-fast: dirs
	$(BLENDER_BG) --python "poster/render.py" -- \
	  "$(MANIFEST)" \
	  --output "$(OUT_DIR)/poster_preview_fast_$(PREVIEW_FAST_PPI)ppi.png" \
	  --ppi "$(PREVIEW_FAST_PPI)" \
	  --engine "$(PREVIEW_FAST_ENGINE)" \
	  --eevee-samples "$(PREVIEW_FAST_EEVEE_SAMPLES)"

.PHONY: render-preview-debug
render-preview-debug:
	$(MAKE) render-preview BLENDER_DEBUG=--debug-cycles

.PHONY: render-final
render-final: dirs
	$(BLENDER_BG) --python "poster/render.py" -- \
	  "$(MANIFEST)" \
	  --output "$(OUT_DIR)/poster_final_$(FINAL_PPI)ppi.png" \
	  --ppi "$(FINAL_PPI)"

.PHONY: render
render: dirs
	: $${PPI:?Usage: make render PPI=200 OUT=out/poster_200ppi.png}
	: $${OUT:?Usage: make render PPI=200 OUT=out/poster_200ppi.png}
	$(BLENDER_BG) --python "poster/render.py" -- \
	  "$(MANIFEST)" \
	  --output "$(OUT)" \
	  --ppi "$(PPI)"

# --------------------------
# Materials (hybrid link->bake)
# --------------------------

# Build/update the material library .blend + catalog JSON
.PHONY: materials-build
materials-build: dirs
	$(BLENDER_BG) --python "$(MATERIAL_BUILD_SCRIPT)" -- \
	  --library "$(MATERIAL_LIBRARY)" \
	  --catalog "$(MATERIAL_CATALOG)" \
	  --recipes "$(MATERIAL_RECIPES)"

# Link materials from the library into the dev asset (keeps live link)
.PHONY: materials-link
materials-link: dirs
	$(BLENDER_BG) --python "$(MATERIAL_SYNC_SCRIPT)" -- \
	  --mode link \
	  --asset "$(DEV_ASSET)" \
	  --library "$(MATERIAL_LIBRARY)" \
	  --materials "$(MATERIAL_GLOB)"

# Bake linked materials in the dev asset to local materials and write compiled asset.
# By default this also packs resources (MATERIAL_PACK=1).
.PHONY: materials-bake
materials-bake: dirs
	$(BLENDER_BG) --python "$(MATERIAL_SYNC_SCRIPT)" -- \
	  --mode bake \
	  --asset "$(DEV_ASSET)" \
	  --out "$(COMPILED_ASSET)" \
	  $(if $(filter 0 false FALSE no NO,$(MATERIAL_PACK)),--no-pack,--pack)

# Convenience: link then bake in one step
.PHONY: materials-link-then-bake
materials-link-then-bake: dirs
	$(BLENDER_BG) --python "$(MATERIAL_SYNC_SCRIPT)" -- \
	  --mode link_then_bake \
	  --asset "$(DEV_ASSET)" \
	  --out "$(COMPILED_ASSET)" \
	  --library "$(MATERIAL_LIBRARY)" \
	  --materials "$(MATERIAL_GLOB)" \
	  $(if $(filter 0 false FALSE no NO,$(MATERIAL_PACK)),--no-pack,--pack)

.PHONY: clean
clean:
	rm -rf "$(OUT_DIR)"/*

# Build/update the blend assets
.PHONY: motion-ao-blend
motion-ao-blend:
	$(BLENDER_BG) --python assets/build/active-objects/build.py -- \
	assets/build/active-objects/motion-ao-manifest.json \
	--output assets/compiled/blend/motion-ao.blend --debug

.PHONY: stage-blend
stage-blend:
	$(BLENDER_BG) --python assets/build/stage/build.py -- \
	--manifest assets/build/stage/manifest.json \
	--out assets/compiled/blend/stage.blend \
	--layout stacked

