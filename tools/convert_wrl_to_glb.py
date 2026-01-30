"""tools/convert_wrl_to_glb.py

Batch convert VRML2 (.wrl) files into GLB for easier, more reproducible importing.

Usage:
  blender -b --factory-startup -P tools/convert_wrl_to_glb.py -- <in.wrl|in_dir> <out_dir> [scale_factor]

Notes:
- GLB/glTF uses meters as its implied unit.
- If your WRL coordinates are in millimeters, use scale_factor=0.001 (mm -> m).
- This script requires Blender to have a VRML importer available.
  In Blender 5 this is typically provided by the “Web3D X3D/VRML2” extension.
"""

import bpy
import sys
from pathlib import Path


def argv_after_dashes():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def clean_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def enable_vrml_importer():
    # Historically this was the bundled add-on module name.
    # With Blender 5 extensions, it is still commonly exposed under this module name.
    try:
        bpy.ops.preferences.addon_enable(module="io_scene_x3d")
        return True
    except Exception:
        return False


def import_wrl(path: Path):
    # Operator imports .x3d and .wrl
    bpy.ops.import_scene.x3d(filepath=str(path))


def export_glb(path: Path):
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format='GLB',
        use_selection=True,
    )


def main():
    args = argv_after_dashes()
    if len(args) < 2:
        raise SystemExit(
            "Usage:\n"
            "  blender -b --factory-startup -P tools/convert_wrl_to_glb.py -- <in.wrl|in_dir> <out_dir> [scale_factor]\n\n"
            "Examples:\n"
            "  # WRL coordinates are in millimeters:\n"
            "  blender -b --factory-startup -P tools/convert_wrl_to_glb.py -- assets/src/wrl assets/compiled/glb 0.001\n\n"
            "  # WRL coordinates are already meters:\n"
            "  blender -b --factory-startup -P tools/convert_wrl_to_glb.py -- assets/src/wrl assets/compiled/glb 1.0\n"
        )

    inp = Path(args[0])
    out_dir = Path(args[1])
    scale_factor = float(args[2]) if len(args) >= 3 else 1.0
    out_dir.mkdir(parents=True, exist_ok=True)

    if not enable_vrml_importer():
        raise SystemExit(
            "VRML importer not enabled.\n"
            "In Blender 5, install/enable the 'Web3D X3D/VRML2 format' extension first."
        )

    files = [inp] if inp.is_file() else sorted(inp.glob("*.wrl"))
    if not files:
        raise SystemExit(f"No .wrl files found at: {inp}")

    for f in files:
        clean_scene()

        # Export in meter-space to avoid unit-scale ambiguity
        scene = bpy.context.scene
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.scale_length = 1.0  # treat BU as meters during export

        import_wrl(f)

        bpy.ops.object.select_all(action='SELECT')

        if scale_factor != 1.0:
            for obj in bpy.context.selected_objects:
                obj.scale *= scale_factor
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        out_path = out_dir / (f.stem + ".glb")
        export_glb(out_path)
        print(f"[OK] {f.name} -> {out_path}")


if __name__ == "__main__":
    main()
