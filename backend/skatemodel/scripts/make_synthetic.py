"""Write a synthetic FineFS-format dataset (skeleton/*.npz + annotation/*.json)."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.data.synthetic import write_dataset  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="data/synthetic")
ap.add_argument("--n", type=int, default=40)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--duration-scale", type=float, default=0.4, help="1.0 = real program length")
ap.add_argument("--no-skater", action="store_true", help="omit skater field (tests by-sample fallback)")
a = ap.parse_args()
ids = write_dataset(a.out, a.n, a.seed, a.duration_scale, with_skater=not a.no_skater)
print(f"wrote {len(ids)} synthetic programs to {a.out}")
