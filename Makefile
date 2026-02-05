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

.PHONY: clean
clean:
	rm -rf "$(OUT_DIR)"/*
