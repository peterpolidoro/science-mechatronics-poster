"""tools/materials/material_recipes.py

Define project-wide reusable materials for Cycles/Eevee.

Workflow:
- Edit MATERIAL_SPECS below to add/update materials (keep names stable).
- Run tools/materials/build_library.py to (re)generate the library .blend.

Naming conventions:
- Materials: MAT_<Category>_<Name>
- Node groups (optional): NG_<...>

Tip:
- Keep these materials "physically plausible". Avoid extreme values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import bpy

# ----------------------------
# Material specifications
# ----------------------------

# Simple, robust “starter kit” materials (procedural, no external textures).
# You can add image-texture-based PBR later (and keep textures under
# assets/library/materials/textures/).
MATERIAL_SPECS: Dict[str, Dict[str, Any]] = {
    "MAT_Plastic_Black": {
        "description":
        "Neutral black plastic (moderate roughness, subtle coat).",
        "tags": ["plastic", "black"],
        "shader": "principled",
        "base_color_rgba": [0.03, 0.03, 0.03, 1.0],
        "metallic": 0.0,
        "roughness": 0.45,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.10,
        "coat_roughness": 0.20,
    },
    "MAT_Plastic_White": {
        "description": "Neutral white plastic (slightly glossy).",
        "tags": ["plastic", "white"],
        "shader": "principled",
        "base_color_rgba": [0.90, 0.90, 0.90, 1.0],
        "metallic": 0.0,
        "roughness": 0.35,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.05,
        "coat_roughness": 0.25,
    },
    "MAT_Rubber_Black": {
        "description": "Black rubber (high roughness, low specular).",
        "tags": ["rubber", "black"],
        "shader": "principled",
        "base_color_rgba": [0.02, 0.02, 0.02, 1.0],
        "metallic": 0.0,
        "roughness": 0.80,
        "specular": 0.20,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.50,
    },
    "MAT_Aluminum_Brushed": {
        "description":
        "Brushed aluminum baseline (metallic, moderate roughness).",
        "tags": ["metal", "aluminum"],
        "shader": "principled",
        "base_color_rgba": [0.80, 0.80, 0.82, 1.0],
        "metallic": 1.0,
        "roughness": 0.28,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.25,
    },
    "MAT_Steel_Polished": {
        "description":
        "Polished steel baseline (metallic, low roughness).",
        "tags": ["metal", "steel"],
        "shader": "principled",
        "base_color_rgba": [0.72, 0.74, 0.76, 1.0],
        "metallic": 1.0,
        "roughness": 0.12,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Paint_Red_Gloss": {
        "description": "Glossy red paint (plastic base with coat).",
        "tags": ["paint", "red"],
        "shader": "principled",
        "base_color_rgba": [0.60, 0.05, 0.05, 1.0],
        "metallic": 0.0,
        "roughness": 0.30,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.35,
        "coat_roughness": 0.10,
    },
    "MAT_Paint_Black_PowderCoat": {
        "description":
        "Black powder-coated / painted metal (satin). Good for stepper motor body housings.",
        "tags": ["paint", "black", "satin"],
        "shader": "principled",
        "base_color_rgba": [0.02, 0.02, 0.02, 1.0],
        "metallic": 0.0,
        "roughness": 0.60,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.08,
        "coat_roughness": 0.35,
    },
    "MAT_Aluminum_Cast_Matte": {
        "description":
        "Cast / bead-blasted aluminum (matte, slightly rough). Good for stepper motor end bells & housings.",
        "tags": ["metal", "aluminum", "cast"],
        "shader": "principled",
        "base_color_rgba": [0.78, 0.78, 0.80, 1.0],
        "metallic": 1.0,
        "roughness": 0.55,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.25,
    },
    "MAT_Aluminum_Machined": {
        "description":
        "Machined aluminum (clean, slightly shinier than cast).",
        "tags": ["metal", "aluminum", "machined"],
        "shader": "principled",
        "base_color_rgba": [0.83, 0.83, 0.85, 1.0],
        "metallic": 1.0,
        "roughness": 0.28,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Steel_Black_Oxide": {
        "description":
        "Black-oxide steel for dark fasteners / socket head screws.",
        "tags": ["metal", "steel", "black"],
        "shader": "principled",
        "base_color_rgba": [0.06, 0.06, 0.06, 1.0],
        "metallic": 1.0,
        "roughness": 0.35,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Plastic_Grey": {
        "description":
        "Neutral light-grey plastic (connector housings).",
        "tags": ["plastic", "grey", "gray"],
        "shader": "principled",
        "base_color_rgba": [0.65, 0.65, 0.65, 1.0],
        "metallic": 0.0,
        "roughness": 0.45,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.05,
        "coat_roughness": 0.30,
    },
    "MAT_Gold_Polished": {
        "description": "Polished gold metal (bright, fairly smooth).",
        "tags": ["metal", "gold"],
        "shader": "principled",
        "base_color_rgba": [1.00, 0.77, 0.34, 1.0],
        "metallic": 1.0,
        "roughness": 0.14,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Plastic_Green": {
        "description":
        "Green plastic (slightly glossy; good for housings/buttons).",
        "tags": ["plastic", "green"],
        "shader": "principled",
        "base_color_rgba": [0.06, 0.45, 0.12, 1.0],
        "metallic": 0.0,
        "roughness": 0.42,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.08,
        "coat_roughness": 0.25,
    },
    "MAT_Plastic_Red": {
        "description":
        "Red plastic (slightly glossy; distinct from MAT_Paint_Red_Gloss).",
        "tags": ["plastic", "red"],
        "shader": "principled",
        "base_color_rgba": [0.65, 0.06, 0.06, 1.0],
        "metallic": 0.0,
        "roughness": 0.40,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.10,
        "coat_roughness": 0.22,
    },
    "MAT_Rubber_Blue": {
        "description": "Blue rubber (high roughness, low specular).",
        "tags": ["rubber", "blue"],
        "shader": "principled",
        "base_color_rgba": [0.05, 0.12, 0.55, 1.0],
        "metallic": 0.0,
        "roughness": 0.82,
        "specular": 0.20,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.50,
    },
    "MAT_Acrylic_Clear_LaserCut": {
        "description": "Clear cast acrylic (PMMA) for laser-cut parts. Polished, realistic IOR, slight cool cast.",
        "tags": ["acrylic", "pmma", "clear", "laser-cut", "plastic"],
        "shader": "principled",
        "base_color_rgba": [0.98, 0.99, 1.00, 1.0],
        "metallic": 0.0,
        "roughness": 0.035,
        "specular": 0.50,
        "ior": 1.49,
        "transmission": 1.00,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Acrylic_Clear_LaserCut_EdgePolished": {
        "description":
        "Optional edge-only acrylic for laser-cut edges (slightly lower roughness / more sparkle).",
        "tags": ["acrylic", "edge", "laser-cut", "clear"],
        "shader": "principled",
        "base_color_rgba": [0.98, 0.99, 1.00, 1.0],
        "metallic": 0.0,
        "roughness": 0.020,
        "specular": 0.50,
        "ior": 1.49,
        "transmission": 1.00,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Acrylic_Clear_Frosted": {
        "description":
        "Frosted/matte clear acrylic (light diffusion).",
        "tags": ["acrylic", "frosted", "matte", "clear"],
        "shader": "principled",
        "base_color_rgba": [0.98, 0.99, 1.00, 1.0],
        "metallic": 0.0,
        "roughness": 0.45,
        "specular": 0.50,
        "ior": 1.49,
        "transmission": 1.00,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_PCB_SolderMask_Green_Dark": {
        "description":
        "Dark green solder mask (olive). Slight clearcoat to mimic glossy polymer coating.",
        "tags": ["pcb", "soldermask", "green"],
        "shader": "principled",
        "base_color_rgba": [0.055, 0.135, 0.040, 1.0],
        "metallic": 0.0,
        "roughness": 0.42,
        "specular": 0.50,
        "ior": 1.48,
        "coat": 0.18,
        "coat_roughness": 0.14,
    },
    "MAT_PCB_FR4_Edge": {
        "description":
        "FR4 glass-epoxy edge (board sides). Use on PCB side faces and inside cutouts if exposed.",
        "tags": ["pcb", "fr4", "substrate"],
        "shader": "principled",
        "base_color_rgba": [0.26, 0.17, 0.08, 1.0],
        "metallic": 0.0,
        "roughness": 0.75,
        "specular": 0.35,
        "ior": 1.55,
        "coat": 0.00,
        "coat_roughness": 0.30,
    },
    "MAT_PCB_Silkscreen_White": {
        "description":
        "White silkscreen ink (matte). Good for text/lines if you have separate geometry.",
        "tags": ["pcb", "silkscreen", "ink", "white"],
        "shader": "principled",
        "base_color_rgba": [0.85, 0.85, 0.85, 1.0],
        "metallic": 0.0,
        "roughness": 0.68,
        "specular": 0.45,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.25,
    },
    "MAT_Gold_ENIG_Satin": {
        "description":
        "ENIG-style gold plating (pads/testpoints). Less mirror-like than polished gold.",
        "tags": ["metal", "gold", "enig", "pcb"],
        "shader": "principled",
        "base_color_rgba": [1.00, 0.70, 0.25, 1.0],
        "metallic": 1.0,
        "roughness": 0.28,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Copper_Oxidized": {
        "description":
        "Oxidized copper (for exposed copper features, if any).",
        "tags": ["metal", "copper"],
        "shader": "principled",
        "base_color_rgba": [0.90, 0.38, 0.25, 1.0],
        "metallic": 1.0,
        "roughness": 0.42,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Solder_Tin_Satin": {
        "description":
        "Solder (tin/SAC) satin. Use for solder fillets/joints if modeled.",
        "tags": ["metal", "solder", "tin"],
        "shader": "principled",
        "base_color_rgba": [0.68, 0.70, 0.73, 1.0],
        "metallic": 1.0,
        "roughness": 0.36,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Epoxy_Black_IC": {
        "description":
        "IC package epoxy (matte black). Good for QFP/QFN/SOIC bodies.",
        "tags": ["electronics", "ic", "epoxy", "black"],
        "shader": "principled",
        "base_color_rgba": [0.02, 0.02, 0.02, 1.0],
        "metallic": 0.0,
        "roughness": 0.68,
        "specular": 0.35,
        "ior": 1.50,
        "coat": 0.00,
        "coat_roughness": 0.25,
    },
    "MAT_Ceramic_Capacitor_Beige": {
        "description":
        "Ceramic capacitor body (MLCC) beige/off-white.",
        "tags": ["electronics", "ceramic", "capacitor"],
        "shader": "principled",
        "base_color_rgba": [0.78, 0.74, 0.62, 1.0],
        "metallic": 0.0,
        "roughness": 0.42,
        "specular": 0.50,
        "ior": 1.55,
        "coat": 0.02,
        "coat_roughness": 0.35,
    },
    "MAT_Resistor_Charcoal": {
        "description":
        "SMD resistor body (dark charcoal).",
        "tags": ["electronics", "resistor"],
        "shader": "principled",
        "base_color_rgba": [0.09, 0.09, 0.10, 1.0],
        "metallic": 0.0,
        "roughness": 0.55,
        "specular": 0.45,
        "ior": 1.50,
        "coat": 0.00,
        "coat_roughness": 0.30,
    },
    "MAT_Plastic_Green_TerminalBlock": {
        "description":
        "Bright green terminal-block plastic (satin). Tuned toward common Phoenix-style connectors.",
        "tags": ["plastic", "green", "connector", "terminal"],
        "shader": "principled",
        "base_color_rgba": [0.35, 0.70, 0.35, 1.0],
        "metallic": 0.0,
        "roughness": 0.48,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.10,
        "coat_roughness": 0.25,
    },
    "MAT_Steel_Stainless_Brushed": {
        "description":
        "Brushed stainless steel (USB shells, shields).",
        "tags": ["metal", "steel", "stainless", "brushed"],
        "shader": "principled",
        "base_color_rgba": [0.74, 0.75, 0.77, 1.0],
        "metallic": 1.0,
        "roughness": 0.32,
        "specular": 0.50,
        "ior": 1.45,
        "coat": 0.00,
        "coat_roughness": 0.20,
    },
    "MAT_Plastic_Clear": {
        "description":
        "Clear plastic (LED lenses, lightpipes). Use with proper lighting; looks best in Cycles.",
        "tags": ["plastic", "clear", "transparent"],
        "shader": "principled",
        "base_color_rgba": [1.00, 1.00, 1.00, 1.0],
        "metallic": 0.0,
        "roughness": 0.04,
        "specular": 0.50,
        "ior": 1.49,
        "coat": 0.00,
        "coat_roughness": 0.20,
        "transmission": 1.00,
    },
}

# ----------------------------
# Helpers
# ----------------------------


def _ensure_output_and_principled(nt: bpy.types.NodeTree) -> bpy.types.Node:
    nodes = nt.nodes
    links = nt.links

    out = None
    bsdf = None
    for n in nodes:
        if n.bl_idname == "ShaderNodeOutputMaterial":
            out = n
        elif n.bl_idname == "ShaderNodeBsdfPrincipled":
            bsdf = n

    if out is None:
        out = nodes.new("ShaderNodeOutputMaterial")
        out.location = (300, 0)

    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)

    # Ensure BSDF -> Output link exists
    if "Surface" in out.inputs and "BSDF" in bsdf.outputs:
        have = False
        for l in links:
            if (
                l.from_node == bsdf
                and l.to_node == out
                and l.to_socket == out.inputs["Surface"]
            ):
                have = True
                break
        if not have:
            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    return bsdf


def _set_input(bsdf: bpy.types.Node, names: Sequence[str], value: Any) -> bool:
    """Try multiple input socket names (Principled v1 vs v2)."""
    for nm in names:
        if nm in bsdf.inputs:
            try:
                bsdf.inputs[nm].default_value = value
                return True
            except Exception:
                return False
    return False


def ensure_principled_material(name: str, spec: Dict[str, Any]) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)

    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _ensure_output_and_principled(nt)

    base = spec.get("base_color_rgba", [1.0, 1.0, 1.0, 1.0])
    if len(base) == 3:
        base = [base[0], base[1], base[2], 1.0]

    _set_input(
        bsdf,
        ["Base Color"],
        (float(base[0]), float(base[1]), float(base[2]), float(base[3])),
    )

    if "metallic" in spec:
        _set_input(bsdf, ["Metallic"], float(spec["metallic"]))

    if "roughness" in spec:
        _set_input(bsdf, ["Roughness"], float(spec["roughness"]))

    if "specular" in spec:
        # Principled v2 uses "Specular IOR Level"
        _set_input(
            bsdf,
            ["Specular", "Specular IOR Level"],
            float(spec["specular"]),
        )

    if "ior" in spec:
        _set_input(bsdf, ["IOR"], float(spec["ior"]))

    if "coat" in spec:
        _set_input(
            bsdf,
            ["Clearcoat", "Coat Weight"],
            float(spec["coat"]),
        )

    if "coat_roughness" in spec:
        _set_input(
            bsdf,
            ["Clearcoat Roughness", "Coat Roughness"],
            float(spec["coat_roughness"]),
        )

    # Optional extras (safe if present)
    if "transmission" in spec:
        _set_input(
            bsdf,
            ["Transmission", "Transmission Weight"],
            float(spec["transmission"]),
        )

    if "alpha" in spec:
        _set_input(bsdf, ["Alpha"], float(spec["alpha"]))

    # Keep materials around even if currently unused in the library file
    try:
        mat.use_fake_user = True
    except Exception:
        pass

    return mat


# ----------------------------
# Public API used by build_library.py
# ----------------------------


def create_or_update_all_materials() -> List[bpy.types.Material]:
    """Create/update all materials in MATERIAL_SPECS.

    Returns:
        List of created/updated materials.
    """
    mats: List[bpy.types.Material] = []
    for name, spec in MATERIAL_SPECS.items():
        shader = str(spec.get("shader", "principled")).lower()
        if shader != "principled":
            raise ValueError(f"Unsupported shader type for {name}: {shader}")
        mats.append(ensure_principled_material(name, spec))
    return mats
