import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.models import build_model, count_params  # noqa: E402
from skatemodel.utils.config import load_config  # noqa: E402

cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "configs/base.yaml")
m = build_model(cfg)
print(f"total trainable params: {count_params(m):,}")
for name in ("encoder", "temporal", "cls_head", "reg_head", "elem_head"):
    print(f"  {name:10s} {count_params(getattr(m, name)):>10,}")
