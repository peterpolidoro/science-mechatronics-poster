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
        "description": "Neutral black plastic (moderate roughness, subtle coat).",
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
        "description": "Brushed aluminum baseline (metallic, moderate roughness).",
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
        "description": "Polished steel baseline (metallic, low roughness).",
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
        "description": "Black powder-coated / painted metal (satin). Good for stepper motor body housings.",
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
        "description": "Cast / bead-blasted aluminum (matte, slightly rough). Good for stepper motor end bells & housings.",
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
        "description": "Machined aluminum (clean, slightly shinier than cast).",
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
        "description": "Black-oxide steel for dark fasteners / socket head screws.",
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
        "description": "Neutral light-grey plastic (connector housings).",
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
            if l.from_node == bsdf and l.to_node == out and l.to_socket == out.inputs["Surface"]:
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

    _set_input(bsdf, ["Base Color"], (float(base[0]), float(base[1]), float(base[2]), float(base[3])))

    if "metallic" in spec:
        _set_input(bsdf, ["Metallic"], float(spec["metallic"]))

    if "roughness" in spec:
        _set_input(bsdf, ["Roughness"], float(spec["roughness"]))

    if "specular" in spec:
        # Principled v2 uses "Specular IOR Level"
        _set_input(bsdf, ["Specular", "Specular IOR Level"], float(spec["specular"]))

    if "ior" in spec:
        _set_input(bsdf, ["IOR"], float(spec["ior"]))

    if "coat" in spec:
        _set_input(bsdf, ["Clearcoat", "Coat Weight"], float(spec["coat"]))

    if "coat_roughness" in spec:
        _set_input(bsdf, ["Clearcoat Roughness", "Coat Roughness"], float(spec["coat_roughness"]))

    # Optional extras (safe if present)
    if "transmission" in spec:
        _set_input(bsdf, ["Transmission", "Transmission Weight"], float(spec["transmission"]))

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
    """Create/update all materials in MATERIAL_SPECS. Returns the created/updated materials."""
    mats: List[bpy.types.Material] = []
    for name, spec in MATERIAL_SPECS.items():
        shader = str(spec.get("shader", "principled")).lower()
        if shader != "principled":
            raise ValueError(f"Unsupported shader type for {name}: {shader}")
        mats.append(ensure_principled_material(name, spec))
    return mats
