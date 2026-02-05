import sys
import argparse
from pathlib import Path

import bpy

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
	 sys.path.insert(0, str(THIS_DIR))

from blendlib import apply_manifest


def argv_after_dashes():
	 if "--" in sys.argv:
	 	 return sys.argv[sys.argv.index("--") + 1:]
	 return []


def parse_args():
	 p = argparse.ArgumentParser(description="Render the poster reproducibly from manifest.json")
	 p.add_argument("manifest", help="Path to poster/manifest.json")
	 p.add_argument("--output", required=True, help="Output image path (PNG recommended)")
	 p.add_argument("--ppi", type=float, default=None, help="Override poster PPI for resolution")

	 # Optional overrides for fast iteration / debugging
	 p.add_argument("--engine", default=None,
	 	 help="Override render engine (CYCLES, BLENDER_EEVEE_NEXT, BLENDER_EEVEE)")
	 p.add_argument("--eevee-samples", type=int, default=None,
	 	 help="Override Eevee render samples (taa_render_samples)")
	 p.add_argument("--cycles-samples", type=int, default=None,
	 	 help="Override Cycles samples")
	 p.add_argument("--no-denoise", action="store_true",
	 	 help="Disable Cycles denoising for faster previews")

	 return p.parse_args(argv_after_dashes())


def set_engine_override(scene, engine_name):
	 if not engine_name:
	 	 return
	 key = engine_name.upper()
	 if key in ("EEVEE", "BLENDER_EEVEE"):
	 	 candidates = ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"]
	 elif key in ("EEVEE_NEXT", "BLENDER_EEVEE_NEXT"):
	 	 candidates = ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]
	 elif key == "CYCLES":
	 	 candidates = ["CYCLES"]
	 else:
	 	 candidates = [engine_name]

	 for c in candidates:
	 	 try:
	 	 	 scene.render.engine = c
	 	 	 print(f"[render.py] Engine override -> {c}")
	 	 	 return
	 	 except Exception:
	 	 	 pass

	 print(f"[render.py] WARN: Could not set engine override {engine_name!r}")


def print_cycles_device_info():
	 scene = bpy.context.scene
	 if scene.render.engine != "CYCLES":
	 	 print(f"[render.py] Render engine = {scene.render.engine} (not Cycles)")
	 	 return

	 try:
	 	 print(f"[render.py] Cycles scene.cycles.device = {scene.cycles.device}")
	 except Exception:
	 	 pass

	 try:
	 	 addon = bpy.context.preferences.addons.get("cycles")
	 	 if not addon:
	 	 	 print("[render.py] Cycles addon prefs not found")
	 	 	 return
	 	 prefs = addon.preferences
	 	 try:
	 	 	 prefs.get_devices()
	 	 except Exception:
	 	 	 try:
	 	 	 	 prefs.refresh_devices()
	 	 	 except Exception:
	 	 	 	 pass

	 	 enabled = []
	 	 for d in getattr(prefs, "devices", []):
	 	 	 if getattr(d, "use", False):
	 	 	 	 enabled.append(f"{d.type}:{d.name}")
	 	 print(f"[render.py] Cycles prefs.compute_device_type = {getattr(prefs,'compute_device_type',None)}")
	 	 print(f"[render.py] Enabled Cycles devices: {enabled}")
	 except Exception as e:
	 	 print(f"[render.py] Could not query Cycles devices: {e!r}")


def main():
	 args = parse_args()

	 out_path = Path(args.output).resolve()
	 out_path.parent.mkdir(parents=True, exist_ok=True)

	 # Build scene from manifest (this also configures Cycles GPU devices)
	 apply_manifest(args.manifest, ppi_override=args.ppi)

	 scene = bpy.context.scene

	 # Apply optional engine/sample overrides AFTER manifest
	 if args.engine:
	 	 set_engine_override(scene, args.engine)

	 if scene.render.engine == "CYCLES":
	 	 if args.cycles_samples is not None:
	 	 	 try:
	 	 	 	 scene.cycles.samples = int(args.cycles_samples)
	 	 	 	 print(f"[render.py] Cycles samples override = {scene.cycles.samples}")
	 	 	 except Exception:
	 	 	 	 pass
	 	 if args.no_denoise:
	 	 	 try:
	 	 	 	 scene.cycles.use_denoising = False
	 	 	 except Exception:
	 	 	 	 pass
	 	 	 try:
	 	 	 	 bpy.context.view_layer.cycles.use_denoising = False
	 	 	 except Exception:
	 	 	 	 pass
	 	 	 print("[render.py] Cycles denoising disabled")

	 elif scene.render.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
	 	 if args.eevee_samples is not None:
	 	 	 try:
	 	 	 	 scene.eevee.taa_render_samples = int(args.eevee_samples)
	 	 	 	 print(f"[render.py] Eevee samples = {scene.eevee.taa_render_samples}")
	 	 	 except Exception:
	 	 	 	 print("[render.py] WARN: Could not set Eevee samples")

	 scene.render.filepath = str(out_path)

	 print(f"[render.py] Final render engine = {scene.render.engine}")
	 print_cycles_device_info()

	 bpy.ops.render.render(write_still=True)
	 print(f"[render.py] Wrote render: {out_path}")


if __name__ == "__main__":
	 main()
