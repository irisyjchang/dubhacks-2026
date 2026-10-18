"""Create splits.json (official split if present, else 70/15/15 grouped by skater, stratified)."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.data.splits import make_splits  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--data-root", required=True)
ap.add_argument("--out", default="splits.json")
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
make_splits(a.data_root, a.out, a.seed)
print(json.dumps(json.load(open(a.out))["_info"], indent=1))
