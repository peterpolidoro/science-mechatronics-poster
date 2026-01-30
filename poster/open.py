import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from blendlib import apply_manifest


def argv_after_dashes():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def main():
    args = argv_after_dashes()
    if args:
        manifest_path = args[0]
    else:
        # Default: repo_root/poster/manifest.json
        manifest_path = str((THIS_DIR / "manifest.json").resolve())

    apply_manifest(manifest_path)
    print(f"[open.py] Applied manifest: {manifest_path}")
    print("[open.py] You can now edit the scene interactively. Re-run 'make open' to re-apply manifest changes.")


if __name__ == "__main__":
    main()
