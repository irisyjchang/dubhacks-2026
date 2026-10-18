import numpy as np
import pytest

from skatemodel.data.elements import parse_element
from skatemodel.metrics import segment_map, spearman
from skatemodel.physics import analyze_jump
from skatemodel.scoring.base_values import element_bv


@pytest.mark.parametrize("code,types,rots,urs,fall,comb,invalid", [
    ("3Lz+3T", ["Lz", "T"], [3, 3], ["", ""], False, 1, False),
    ("4S<", ["S"], [4], ["<"], False, 0, False),
    ("2A*", ["A"], [2], [""], False, 0, True),
    ("3F+1Eu+3S", ["F", "Lo", "S"], [3, 1, 3], ["", "", ""], False, 2, False),
    ("4T<< F", ["T"], [4], ["<<"], True, 0, False),
    ("3Aq", ["A"], [3], ["q"], False, 0, False),
    ("3Lze", ["Lz"], [3], [""], False, 0, False),
    ("3A+2A+SEQ", ["A", "A"], [3, 2], ["", ""], False, 3, False),
    ("3FF", ["F"], [3], [""], True, 0, False),
])
def test_parse_jumps(code, types, rots, urs, fall, comb, invalid):
    el = parse_element(code)
    assert el.kind == "jump"
    assert [j.type for j in el.jumps] == types
    assert [j.rotations for j in el.jumps] == rots
    assert [j.ur for j in el.jumps] == urs
    assert el.fall == fall and el.comb == comb and el.invalid == invalid


def test_info_marks_and_bonus():
    el = parse_element("3F+1Eu+3S", infos=[["x"], ["x"], ["x"]], jump_comb=2)
    assert el.bonus and el.jumps[1].euler
    assert element_bv(el) == pytest.approx(11.11)  # appendix example
    el = parse_element("4T+3T", infos=[["<"], 0, 0])
    assert el.jumps[0].ur == "<" and element_bv(el) == pytest.approx(9.5 * 0.8 + 4.2)
    el = parse_element("3A", infos=[["F"], 0, 0])
    assert el.fall


def test_non_jumps():
    el = parse_element("CCoSp4")
    assert el.kind == "spin" and el.spin_code == "CCoSp" and el.level == "4"
    assert element_bv(el) == pytest.approx(3.5)
    el = parse_element("StSq3", coarse_class="sequence")
    assert el.kind == "step" and element_bv(el) == pytest.approx(3.3)
    el = parse_element("FCSp3V")
    assert el.v_reduced


def test_physics_ballistic():
    fps, h = 25.0, 0.5
    t_air = np.sqrt(8 * h / 9.81)
    T = 200
    pos = np.zeros((T, 17, 3))
    pos[:, :, 1] = 1.0
    pos[:, [3, 6], 1] = 0.0
    pos[:, 4, 0], pos[:, 1, 0] = 0.1, -0.1
    pos[:, 0, 0] = np.linspace(0, 10, T)  # global motion
    a = 100
    n = int(round(t_air * fps))
    for i in range(n):
        u = (i + 0.5) / n
        pos[a + i, :, 1] += 4 * h * u * (1 - u) + 0.05
    r = analyze_jump(pos, a - 10, a + n + 10, fps)
    assert r["valid"] and abs(r["air_time_s"] - t_air) < 2 / fps
    assert abs(r["height_m"] - h) < 0.15


def test_metrics():
    dets = [[(0, 10, 20, 0.9), (0, 50, 60, 0.4)]]
    gts = [[(0, 10, 21), (1, 100, 120)]]
    m = segment_map(dets, gts, 2)
    assert m["AP@0.5/c0"] == pytest.approx(1.0)
    assert m["AP@0.5/c1"] == 0.0
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)


def test_synthetic_roundtrip(tmp_path):
    from skatemodel.data.dataset import ProgramStore, WindowDataset, collate
    from skatemodel.data.synthetic import write_dataset
    ids = write_dataset(str(tmp_path), n=2, duration_scale=0.3)
    store = ProgramStore(str(tmp_path), ids)
    ds = WindowDataset(store, 256, 128, train=True, noise=True, aug_cfg={})
    b = collate([ds[0], ds[1]])
    assert b["x"].shape == (2, 256, 17, 15)
    assert b["segs"].shape[1] == 3
    for p in store.programs:
        # parsed BV must reproduce the annotated BV (incl. x bonus)
        for e in p.ann.elements:
            assert element_bv(e.parsed) == pytest.approx(e.bv, abs=0.011)


def test_batched_materialize_matches_per_sample(tmp_path):
    import torch
    from skatemodel.data.dataset import ProgramStore, WindowDataset, collate, materialize_batch
    from skatemodel.data.synthetic import write_dataset
    ids = write_dataset(str(tmp_path), n=2, duration_scale=0.3)
    store = ProgramStore(str(tmp_path), ids)
    a = WindowDataset(store, 128, 64, train=True, noise=False, materialize=True)
    b = WindowDataset(store, 128, 64, train=True, noise=False, materialize=False)
    items = [a[0], a[3]]
    batch = collate([b[0], b[3]])
    x = materialize_batch(store.tensors("cpu"), batch["plan"], {}, True)
    assert torch.allclose(x, torch.stack([it["x"] for it in items]), atol=1e-5)
    # noisy plans also run batched
    c = WindowDataset(store, 128, 64, train=True, noise=True, materialize=False)
    xb = materialize_batch(store.tensors("cpu"), collate([c[0], c[1]])["plan"], {}, True)
    assert torch.isfinite(xb).all()


def test_mmfs_classes_and_layout():
    from skatemodel.data.mmfs import MMFS_CLASSES, class_kind, coco2d_to_h36m
    for i, code in enumerate(MMFS_CLASSES):
        el = parse_element(code, coarse_class=class_kind(i))
        assert el.kind == class_kind(i)
        assert element_bv(el) > 0, code
        if el.kind == "jump":
            assert all(j.rotations >= 1 for j in el.jumps)
    coco = np.random.rand(10, 17, 3).astype(np.float32) + 0.5
    h = coco2d_to_h36m(coco)
    assert h.shape == (10, 17, 3) and np.all(h[..., 2] == 0)
    assert np.allclose(h[:, 0, :2], (coco[:, 11, :2] + coco[:, 12, :2]) / 2)
