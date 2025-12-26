#!/usr/bin/env hython
"""
Houdini + hython batch rendering tool:
- Loads a hip file
- Sweeps roughness + light intensity + pixel samples
- Optional turntable rendering (multiple frames)
- Writes organized outputs
- Logs render metadata to CSV
- (Optional) builds a contact sheet if Pillow is installed

Run:
  hython render_sweep.py --hip scene.hipnc --rop /out/karma1 --mat /mat/test_material --light /obj/env_light
"""

from __future__ import annotations
import argparse
import csv
import itertools
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Iterable

import hou


# --------------------------- helpers ---------------------------

def require_node(path: str) -> hou.Node:
    n = hou.node(path)
    if n is None:
        raise RuntimeError(f"Missing node: {path}")
    return n

def require_parm(node: hou.Node, parm_name: str) -> hou.Parm:
    p = node.parm(parm_name)
    if p is None:
        raise RuntimeError(
            f"Missing parm '{parm_name}' on {node.path()}. "
            f"(Houdini UI: right-click parm -> Copy Parameter -> Copy Parameter Name)"
        )
    return p

def find_parm_by_label_contains(node: hou.Node, needles: Iterable[str]) -> Optional[hou.Parm]:
    needles = [n.lower() for n in needles]
    for p in node.parms():
        label = (p.description() or "").lower()
        name = p.name().lower()
        if any(n in label for n in needles) or any(n in name for n in needles):
            return p
    return None

def find_output_picture_parm(rop: hou.Node) -> hou.Parm:
    # Try common parm names first
    candidates = [
        "picture", "outputpicture", "output_picture", "vm_picture", "ri_picture", "filename", "image"
    ]
    for name in candidates:
        p = rop.parm(name)
        if p is not None:
            return p

    # Then search by label/name heuristics
    p = find_parm_by_label_contains(rop, ["output picture", "picture"])
    if p:
        return p

    raise RuntimeError(
        f"Could not locate Output Picture parm on {rop.path()}.\n"
        f"UI fallback: right-click Output Picture field -> Copy Parameter -> Copy Parameter Name"
    )

def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def try_import_pillow():
    try:
        from PIL import Image  # type: ignore
        return Image
    except Exception:
        return None


# --------------------------- config ---------------------------

@dataclass(frozen=True)
class SweepConfig:
    roughness: tuple[float, ...]
    light_intensity: tuple[float, ...]
    pixel_samples: tuple[int, ...]
    turntable_frames: int
    turntable_degrees: float


# --------------------------- core logic ---------------------------

def set_pixel_samples(rop: hou.Node, samples: int) -> str:
    """
    Karma sample parm naming varies. We try a few common ones,
    then fall back to label search.
    """
    candidates = ["pxsamples", "karma_pixelsamples", "pixel_samples", "pixelsamples", "samplesperpixel"]
    for c in candidates:
        p = rop.parm(c)
        if p is not None:
            p.set(int(samples))
            return p.name()

    p = find_parm_by_label_contains(rop, ["pixel samples", "samples per pixel", "samples/pixel"])
    if p is not None:
        p.set(int(samples))
        return p.name()

    # Not fatal — log that we couldn't set it
    return "<not_found>"

def rotate_camera_turntable(cam: hou.Node, frame_idx: int, total_frames: int, degrees: float) -> None:
    """
    Simple turntable: rotate camera around Y axis by degrees over total_frames.
    This assumes your camera is already positioned looking at the object.
    """
    if total_frames <= 1:
        return
    frac = frame_idx / (total_frames - 1)
    ry = frac * degrees

    ry_parm = cam.parm("ry")
    if ry_parm is None:
        # Some camera rigs might not expose ry at OBJ level; ignore silently
        return
    ry_parm.set(float(ry))

def render_one(
    rop: hou.Node,
    out_picture_parm: hou.Parm,
    frame: int,
) -> None:
    # Render exactly one frame
    rop.render(frame_range=(frame, frame))

def build_contact_sheet(outputs_dir: Path, glob_pattern: str = "*.png", cols: int = 5) -> Optional[Path]:
    Image = try_import_pillow()
    if Image is None:
        return None

    images = sorted(outputs_dir.glob(glob_pattern))
    if not images:
        return None

    thumbs = []
    for p in images:
        im = Image.open(p).convert("RGB")
        im.thumbnail((480, 480))
        thumbs.append((p.name, im))

    # Grid size
    rows = (len(thumbs) + cols - 1) // cols
    w = max(t[1].size[0] for t in thumbs)
    h = max(t[1].size[1] for t in thumbs)

    sheet = Image.new("RGB", (cols * w, rows * h))
    for i, (_, im) in enumerate(thumbs):
        x = (i % cols) * w
        y = (i // cols) * h
        sheet.paste(im, (x, y))

    out_path = outputs_dir / "contact_sheet.png"
    sheet.save(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hip", default="scene.hipnc", help="Hip file name/path")
    ap.add_argument("--rop", default="/out/karma1", help="Karma ROP path (e.g. /out/karma1)")
    ap.add_argument("--mat", default="/mat/test_material", help="Material node path (Principled Shader)")
    ap.add_argument("--rough_parm", default="rough", help="Roughness parm name on the material node")
    ap.add_argument("--light", default="/obj/env_light", help="Light node path (env light or area light)")
    ap.add_argument("--light_int_parm", default="light_intensity", help="Light intensity parm name (may differ)")
    ap.add_argument("--cam", default="/obj/render_cam", help="Camera node path for optional turntable")
    ap.add_argument("--outdir", default="outputs", help="Output directory")
    ap.add_argument("--make_contact_sheet", action="store_true", help="Build contact sheet (requires Pillow)")
    args = ap.parse_args()

    proj_dir = Path(os.getcwd()).resolve()
    hip_path = Path(args.hip).expanduser()
    if not hip_path.is_absolute():
        hip_path = (proj_dir / hip_path).resolve()

    if not hip_path.exists():
        raise RuntimeError(f"Hip file not found: {hip_path}")

    outdir = Path(args.outdir)
    if not outdir.is_absolute():
        outdir = (proj_dir / outdir).resolve()
    safe_mkdir(outdir)

    print(f"Loading hip: {hip_path}")
    hou.hipFile.load(str(hip_path))

    rop = require_node(args.rop)
    mat = require_node(args.mat)
    light = require_node(args.light)
    cam = require_node(args.cam)

    rough_parm = require_parm(mat, args.rough_parm)

    # Light intensity parm can vary; we try user-provided first, then search
    light_int_parm = light.parm(args.light_int_parm)
    if light_int_parm is None:
        light_int_parm = find_parm_by_label_contains(light, ["intensity"])
    if light_int_parm is None:
        raise RuntimeError(
            f"Could not find light intensity parm on {light.path()}.\n"
            f"Try right-clicking the Intensity field -> Copy Parameter Name, then pass --light_int_parm <name>."
        )

    out_picture_parm = find_output_picture_parm(rop)
    print(f"Output picture parm: {out_picture_parm.name()} (label: {out_picture_parm.description()})")

    # ----- the “complex” sweep setup -----
    cfg = SweepConfig(
        roughness=(0.1, 0.3, 0.5, 0.7, 0.9),
        light_intensity=(1.5, 2.5, 3.5),     # pick values that look good in your scene
        pixel_samples=(16, 32),              # low/high to show quality vs speed
        turntable_frames=12,                 # 1 = stills only, 12 = short turntable
        turntable_degrees=360.0,
    )

    # metadata log
    csv_path = outdir / "render_log.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "roughness", "light_intensity", "pixel_samples",
            "frame", "output_file", "pixel_samples_parm_used", "seconds"
        ])

        combos = list(itertools.product(cfg.roughness, cfg.light_intensity, cfg.pixel_samples))
        print(f"Total variations: {len(combos)}; frames per variation: {cfg.turntable_frames}")

        for (r, li, ps) in combos:
            rough_parm.set(float(r))
            light_int_parm.set(float(li))
            ps_parm_used = set_pixel_samples(rop, int(ps))

            # Folder per variation (production style)
            var_dir = outdir / f"rough_{r:.2f}" / f"light_{li:.2f}" / f"spp_{ps:03d}"
            safe_mkdir(var_dir)

            for frame_idx in range(cfg.turntable_frames):
                frame = 1 + frame_idx
                rotate_camera_turntable(cam, frame_idx, cfg.turntable_frames, cfg.turntable_degrees)

                out_file = var_dir / f"frame_{frame:04d}.png"
                out_picture_parm.set(str(out_file))

                t0 = time.time()
                render_one(rop, out_picture_parm, frame)
                dt = time.time() - t0

                writer.writerow([f"{r:.2f}", f"{li:.2f}", ps, frame, str(out_file), ps_parm_used, f"{dt:.3f}"])
                print(f"Rendered r={r:.2f}, li={li:.2f}, spp={ps}, frame={frame:04d} -> {out_file.name} ({dt:.2f}s)")

    print(f"Saved render log: {csv_path}")

    # Optional: build a quick contact sheet for the top-level outputs folder only.
    # (This is most useful if you render stills; for turntables it will pick many frames.)
    if args.make_contact_sheet:
        sheet = build_contact_sheet(outdir, glob_pattern="**/frame_0001.png", cols=6)
        if sheet:
            print(f"Contact sheet created: {sheet}")
        else:
            print("Contact sheet skipped (no images found or Pillow not installed).")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
