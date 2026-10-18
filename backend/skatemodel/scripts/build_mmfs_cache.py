"""Align MMFS clips to their full programs and write the training cache (run once, ~1-2 min).

    python scripts/build_mmfs_cache.py --mmfs-root ../data/mmfs/MMFS --out data/mmfs_cache [--max-programs 40]
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.data.mmfs import build_cache  # noqa: E402

logging.basicConfig(level=logging.INFO)
ap = argparse.ArgumentParser()
ap.add_argument("--mmfs-root", required=True, help="dir containing skeleton/ (or the skeleton dir itself)")
ap.add_argument("--out", default="data/mmfs_cache")
ap.add_argument("--max-programs", type=int, default=0, help="subset for quick local tests")
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
print(json.dumps(build_cache(a.mmfs_root, a.out, a.max_programs, seed=a.seed), indent=1))
