#!/usr/bin/env hython
import os
import sys
from pathlib import Path

import hou


HIP_FILE = "scene.hipnc"             
KARMA_ROP_PATH = "/out/karma1"          
MATERIAL_NODE_PATH = "/mat/test_material"  
ROUGHNESS_PARM_NAME = "rough"     

def require_node(path: str) -> hou.Node:
    node = hou.node(path)
    if node is None:
        raise RuntimeError(f"Could not find node at: {path}")
    return node


def require_parm(node: hou.Node, parm_name: str) -> hou.Parm:
    parm = node.parm(parm_name)
    if parm is None:
        raise RuntimeError(
            f"Could not find parm '{parm_name}' on node: {node.path()}\n"
            f"Tip: Right-click the parameter in Houdini -> Copy Parameter -> Copy Parameter Name"
        )
    return parm

def find_output_picture_parm(rop: hou.Node) -> hou.Parm:
    """
    Karma ROP parameter names vary by version. Try common candidates and
    finally search by label containing 'Output Picture' or 'Picture'.
    """
    # Common internal parm names seen across Karma/Render nodes
    candidates = [
        "picture",          # sometimes used
        "vm_picture",       # Mantra-style (often not present on Karma)
        "outputpicture",    # possible
        "output_picture",   # possible
        "ri_picture",       # possible
        "image",            # possible
        "filename",         # possible
    ]

    for name in candidates:
        p = rop.parm(name)
        if p is not None:
            return p

    # Search all parms by UI label
    for p in rop.parms():
        label = (p.description() or "").lower()
        name = p.name().lower()
        if "output picture" in label or ("picture" in label and "output" in label):
            return p
        if "output picture" in name or ("picture" in name and "output" in name):
            return p

    # As a final attempt, look for any parm whose label is exactly "Picture"
    for p in rop.parms():
        if (p.description() or "").strip().lower() == "picture":
            return p

    raise RuntimeError(
        f"Could not locate an output image parm on {rop.path()}.\n"
        f"Next step: in Houdini UI, right-click the Output Picture field -> "
        f"Copy Parameter -> Copy Parameter Name, then tell me what you got."
    )



def main() -> int:
    # Resolve project directory (folder containing this script)
    proj_dir = Path(__file__).resolve().parent
    hip_path = (proj_dir / HIP_FILE).resolve()

    if not hip_path.exists():
        print(f"ERROR: Hip file not found: {hip_path}")
        return 1

    # Create output directory
    renders_dir = proj_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    # Load scene
    print(f"Loading hip: {hip_path}")
    hou.hipFile.load(str(hip_path))

    karma = require_node(KARMA_ROP_PATH)
    mat = require_node(MATERIAL_NODE_PATH)
    rough_parm = require_parm(mat, ROUGHNESS_PARM_NAME)

    # Karma output parm is typically named "vm_picture" even though UI says "Output Picture"
    out_parm = find_output_picture_parm(karma)
    print(f"Using output parm: {out_parm.name()}  (label: {out_parm.description()})")


    # Sweep values (edit if you want)
    roughness_values = [0.1, 0.3, 0.5, 0.7, 0.9]

    print("Starting roughness sweep...")
    for r in roughness_values:
        rough_parm.set(float(r))

        out_file = renders_dir / f"roughness_{r:.2f}.png"
        out_parm.set(str(out_file))

        print(f"  Rendering roughness={r:.2f} -> {out_file.name}")
        # Render current frame (still)
        karma.render(frame_range=(hou.frame(), hou.frame()))

    # Save hip with changes (optional; comment out if you don't want this)
    # hou.hipFile.save()

    print(f"Done. Outputs in: {renders_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"\nFAILED: {e}\n")
        raise
