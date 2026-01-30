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
    return p.parse_args(argv_after_dashes())


def main():
    args = parse_args()

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    apply_manifest(args.manifest, ppi_override=args.ppi)

    scene = bpy.context.scene
    scene.render.filepath = str(out_path)

    # Render still
    bpy.ops.render.render(write_still=True)
    print(f"[render.py] Wrote render: {out_path}")


if __name__ == "__main__":
    main()
