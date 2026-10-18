"""Inspect real FineFS files to verify the assumptions in skatemodel/data/finefs_io.py.

    python scripts/inspect_finefs.py --data-root data/finefs [--n 3]

Prints npz keys/shapes, bone-length stats (joint-order sanity check), root-relative check,
raw annotation keys, element time ranges, and whether parsed BVs reproduce annotated BVs.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.data import finefs_io  # noqa: E402
from skatemodel.data.skeleton import EDGES, JOINT_NAMES  # noqa: E402
from skatemodel.scoring.base_values import element_bv  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--data-root", required=True)
ap.add_argument("--n", type=int, default=3)
a = ap.parse_args()

root = a.data_root
print("top-level entries:", sorted(os.listdir(root))[:20])
sk_dir = os.path.join(root, finefs_io.SKELETON_DIR)
an_dir = os.path.join(root, finefs_io.ANNOTATION_DIR)
for d in (sk_dir, an_dir):
    print(d, "exists" if os.path.isdir(d) else "MISSING", (sorted(os.listdir(d))[:5] if os.path.isdir(d) else ""))
if not os.path.isdir(sk_dir):
    sys.exit("fix SKELETON_DIR in finefs_io.py")

files = sorted(f for f in os.listdir(sk_dir) if f.endswith(".npz"))[: a.n]
for f in files:
    z = np.load(os.path.join(sk_dir, f), allow_pickle=True)
    print(f"\n== {f}: keys", {k: (z[k].shape, str(z[k].dtype)) for k in z.keys()})
    try:
        x = finefs_io.load_skeleton(os.path.join(sk_dir, f))
    except Exception as e:
        print("  load_skeleton FAILED:", e)
        continue
    print(f"  loaded {x.shape}, duration {x.shape[0] / finefs_io.FPS:.1f}s @ {finefs_io.FPS} fps, "
          f"range {x.min():.2f}..{x.max():.2f}")
    print("  pelvis std per axis:", x[:, 0].std(0).round(3), "(all ~0 => root-relative skeleton)")
    print("  mean bone lengths (expect legs ~0.4-0.45 m, left~right if order is H36M):")
    for c, p in EDGES:
        L = np.linalg.norm(x[:, c] - x[:, p], axis=-1).mean()
        print(f"    {JOINT_NAMES[p]:>11s}->{JOINT_NAMES[c]:<11s} {L:.3f}")
    sid = f[:-4]
    ap_ = finefs_io.annotation_path(root, sid)
    if ap_ is None:
        print("  NO annotation found for", sid, "(fix ANNOTATION_DIR/ANNOTATION_EXTS)")
        continue
    raw = finefs_io.load_annotation_raw(ap_)
    print("  annotation keys:", list(raw.keys()))
    ex = raw.get("executed_element", {})
    first = next(iter(ex.values())) if isinstance(ex, dict) and ex else (ex[0] if ex else {})
    print("  first element raw:", json.dumps(first)[:400])
    ann = finefs_io.parse_annotation(raw, sid)
    print(f"  competition={ann.competition} type={ann.program_type} gender={ann.gender} TES={ann.tes} skater={ann.skater}")
    tot = 0.0
    for e in ann.elements:
        bv = element_bv(e.parsed)
        tot += e.score_of_panel
        flag = "" if abs(bv - e.bv) < 0.02 else f"   <-- BV lookup {bv:.2f} != annotated {e.bv:.2f}"
        print(f"    {e.index:2d} {e.name:<18s} {e.coarse_class:5s} comb={e.jump_comb:2d} "
              f"t={e.start_frame / finefs_io.FPS:6.1f}-{e.end_frame / finefs_io.FPS:6.1f}s "
              f"({(e.end_frame - e.start_frame) / finefs_io.FPS:4.1f}s) bv={e.bv:5.2f} goe={e.goe:5.2f} "
              f"fall={e.parsed.fall}{flag}")
    print(f"  sum(score_of_panel)={tot:.2f} vs TES={ann.tes}")
