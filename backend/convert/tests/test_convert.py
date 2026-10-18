import numpy as np
import pytest

from convert import config as C
from convert import skeleton, swaps, temporal
from convert.pipeline import process_landmarks

IDX = C.joint_index()


def make_landmarks(T=100, seed=0):
    """Synthetic 33-landmark sequence: a standing figure swaying + moving arms."""
    rng = np.random.default_rng(seed)
    t = np.arange(T) / 25.0
    W = np.zeros((T, 33, 3))
    base = {0: (0, -0.65, -0.05), 7: (0.07, -0.62, 0.0), 8: (-0.07, -0.62, 0.0),
            11: (0.2, -0.5, 0), 12: (-0.2, -0.5, 0),
            13: (0.25, -0.25, 0), 14: (-0.25, -0.25, 0),
            15: (0.27, -0.0, 0), 16: (-0.27, -0.0, 0),
            23: (0.1, 0, 0), 24: (-0.1, 0, 0),
            25: (0.1, 0.45, 0), 26: (-0.1, 0.45, 0),
            27: (0.1, 0.9, 0), 28: (-0.1, 0.9, 0)}
    for k, v in base.items():
        W[:, k] = v
    # L/R asymmetric motion so swaps are detectable (left leg swings in z)
    W[:, 25, 2] += 0.15 * np.sin(2 * np.pi * 0.8 * t)
    W[:, 27, 2] += 0.3 * np.sin(2 * np.pi * 0.8 * t)
    W[:, 26, 2] -= 0.15 * np.sin(2 * np.pi * 0.8 * t)
    W[:, 28, 2] -= 0.3 * np.sin(2 * np.pi * 0.8 * t)
    W[:, 15, 1] -= 0.1 * np.sin(2 * np.pi * 0.5 * t)
    img = np.zeros((T, 33, 3))
    img[..., 0] = 0.5 + W[..., 0] * 0.3
    img[..., 1] = 0.5 + W[..., 1] * 0.3
    vis = np.ones((T, 33))
    return t, W, img, vis


def test_mapping_order_and_values():
    t, W, img, vis = make_landmarks(5)
    X, v = skeleton.map_landmarks(W, img, vis)
    assert X.shape == (5, 17, 5) and v.shape == (5, 17)
    np.testing.assert_allclose(X[:, IDX["pelvis"], :3], (W[:, 23] + W[:, 24]) / 2)
    np.testing.assert_allclose(X[:, IDX["r_hip"], :3], W[:, 24])
    np.testing.assert_allclose(X[:, IDX["l_ankle"], :3], W[:, 27])
    np.testing.assert_allclose(X[:, IDX["thorax"], :3], (W[:, 11] + W[:, 12]) / 2)
    np.testing.assert_allclose(X[:, IDX["spine"], :3],
                               (X[:, IDX["pelvis"], :3] + X[:, IDX["thorax"], :3]) / 2)
    np.testing.assert_allclose(X[:, IDX["neck"], :3], W[:, 0])
    np.testing.assert_allclose(X[:, IDX["l_wrist"], :3], W[:, 15])
    np.testing.assert_allclose(X[:, IDX["r_shoulder"], :3], W[:, 12])
    # canonical H3.6M order
    assert [C.JOINT_ORDER.index(n) for n in ["pelvis", "r_hip", "l_hip", "spine", "head_top",
                                             "l_shoulder", "r_shoulder"]] == [0, 1, 4, 7, 10, 11, 14]


def test_head_top_above_ears():
    t, W, img, vis = make_landmarks(3)
    X, _ = skeleton.map_landmarks(W, img, vis)
    # y is down, so "above" means smaller y than the ear midpoint
    assert (X[:, IDX["head_top"], 1] < (W[:, 7, 1] + W[:, 8, 1]) / 2).all()


def test_mapping_follows_joint_order_edit():
    t, W, img, vis = make_landmarks(3)
    order = list(reversed(C.JOINT_ORDER))
    X, _ = skeleton.map_landmarks(W, img, vis, joint_order=order)
    np.testing.assert_allclose(X[:, order.index("r_knee"), :3], W[:, 26])


def test_axes_presets():
    s = np.array([[[0, 0, 0], [1, 2, 3]]], float)
    out = skeleton.convert_axes(s, "camera_y_up", 1000, joint_order=["pelvis", "x"])
    np.testing.assert_allclose(out[0, 1], [1000, -2000, -3000])
    out = skeleton.convert_axes(s, "camera", 1.0, mirror_x=True, joint_order=["pelvis", "x"])
    np.testing.assert_allclose(out[0, 1], [-1, 2, 3])


def test_resample_30_to_25_linear():
    t = np.arange(61) / 30.0
    x = (2 * t)[:, None, None] * np.ones((1, 2, 3))
    to, xo = temporal.resample(t, x, 25.0)
    assert len(to) == 51
    np.testing.assert_allclose(xo[:, 0, 0], 2 * to, atol=1e-9)


def test_resample_preserves_gaps_and_identity():
    t = np.arange(10) / 25.0
    x = np.arange(10, dtype=float)[:, None, None] * np.ones((1, 1, 2))
    x[4] = np.nan
    to, xo = temporal.resample(t, x, 25.0)
    assert np.isnan(xo[4]).all() and not np.isnan(xo[3]).any() and not np.isnan(xo[5]).any()
    np.testing.assert_allclose(xo[:4, 0, 0], x[:4, 0, 0])


def test_resample_upsample():
    t = np.arange(6) / 10.0
    x = t[:, None, None] * np.ones((1, 1, 1))
    to, xo = temporal.resample(t, x, 25.0)
    np.testing.assert_allclose(xo[:, 0, 0], to, atol=1e-9)


def test_gap_fill_short_and_long():
    T = 60
    t = np.arange(T)
    X = np.stack([np.sin(t / 8.0), t / 60.0, np.zeros(T)], axis=-1)[:, None, :].copy()
    truth = X.copy()
    X[10:14] = np.nan        # short (4)
    X[30:50] = np.nan        # long (20)
    Xf, mask = temporal.fill_gaps(X, max_gap=5, method="pchip")
    assert np.isfinite(Xf).all()
    assert mask[10:14].all() and not mask[30:50].any() and mask[:30].all() and mask[50:].all()
    assert np.abs(Xf[10:14] - truth[10:14]).max() < 0.05
    # long gap bridged linearly between neighbours
    np.testing.assert_allclose(Xf[40, 0], 0.5 * (Xf[29, 0] + Xf[50, 0]) , atol=0.1)


def test_gap_fill_edges():
    X = np.ones((20, 1, 3)) * np.arange(20)[:, None, None]
    X[:2] = np.nan
    X[-10:] = np.nan
    Xf, mask = temporal.fill_gaps(X, max_gap=4)
    assert mask[:2].all() and not mask[-10:].any()
    assert np.isfinite(Xf).all()
    np.testing.assert_allclose(Xf[0], Xf[2])


def test_swap_fix_recovers_labels():
    t, W, img, vis = make_landmarks(100)
    X, _ = skeleton.map_landmarks(W, img, vis)
    clean = X.copy()
    bad = X.copy()
    s = slice(40, 60)
    for r, l in C.SWAP_GROUPS["legs"]["pairs"]:
        bad[s, IDX[r]], bad[s, IDX[l]] = clean[s, IDX[l]].copy(), clean[s, IDX[r]].copy()
    assert np.abs(bad - clean).max() > 0.1
    fixed, info = swaps.fix_lr_swaps(bad)
    np.testing.assert_allclose(fixed, clean, atol=1e-9)
    assert info["legs"][40:60].all() and not info["legs"][:40].any() and not info["arms"].any()


def test_swap_fix_leaves_clean_data_alone():
    t, W, img, vis = make_landmarks(100)
    X, _ = skeleton.map_landmarks(W, img, vis)
    fixed, info = swaps.fix_lr_swaps(X)
    np.testing.assert_allclose(fixed, X)
    assert not any(p.any() for p in info.values())


def test_bone_lengths_enforced():
    t, W, img, vis = make_landmarks(50)
    rng = np.random.default_rng(1)
    X, _ = skeleton.map_landmarks(W + rng.normal(0, 0.02, W.shape), img, vis)
    mask = np.ones(X.shape[:2], bool)
    L = temporal.bone_lengths(X, mask)
    Y = temporal.enforce_bone_lengths(X, L)
    for (p, c), l in L.items():
        d = np.linalg.norm(Y[:, IDX[c], :3] - Y[:, IDX[p], :3], axis=-1)
        np.testing.assert_allclose(d, l, atol=1e-9)
    np.testing.assert_allclose(Y[:, 0], X[:, 0])  # root unchanged


def test_smoothing_reduces_noise_and_keeps_fast_motion():
    fps = 25.0
    t = np.arange(200) / fps
    rng = np.random.default_rng(2)
    for method in ("one_euro", "savgol"):
        # slow motion: noise is reduced
        slow = 0.3 * np.sin(2 * np.pi * 0.5 * t)[:, None]
        noisy = slow + rng.normal(0, 0.015, slow.shape)
        sm = temporal.smooth(noisy, method, fps)
        assert np.abs(sm - slow).mean() < np.abs(noisy - slow).mean()
        # fast motion (1.5 Hz, 0.3 m): amplitude preserved, small error
        fast = 0.3 * np.sin(2 * np.pi * 1.5 * t)[:, None]
        sm = temporal.smooth(fast + rng.normal(0, 0.015, fast.shape), method, fps)
        assert np.abs(sm - fast).mean() < 0.02
        assert np.abs(sm).max() > 0.26


def test_full_process_with_dropouts_and_swap():
    t, W, img, vis = make_landmarks(150)
    W = W.copy(); img = img.copy(); vis = vis.copy()
    W[20:23] = np.nan; img[20:23] = np.nan; vis[20:23] = 0       # undetected
    vis[60:64, 27] = 0.05                                         # one joint low vis
    vis[100:130, 28] = 0.0                                        # long gap
    for a, b in ((25, 26), (27, 28)):                             # swapped legs
        W[70:80, [a, b]] = W[70:80, [b, a]]
    out = process_landmarks(t, W, img, vis, C.PipelineConfig(max_gap=6))
    T = out["skeleton"].shape[0]
    assert out["skeleton"].shape == (T, 17, 3) and out["skeleton"].dtype == np.float32
    assert out["mask"].shape == (T, 17) and out["confidence"].shape == (T,)
    assert out["pelvis_2d"].shape == (T, 2) and float(out["fps"]) == 25.0
    assert np.isfinite(out["skeleton"]).all()
    assert out["mask"][105, IDX["r_ankle"]] == 0 and out["mask"][105, IDX["l_ankle"]] == 1
    assert out["mask"][21].all()                                   # short gap filled
    # swap was repaired: left ankle z keeps its sign during the swap window
    ref = process_landmarks(t, *make_landmarks(150)[1:], C.PipelineConfig(max_gap=6))
    err = np.abs(out["skeleton"][70:80, IDX["l_ankle"]] - ref["skeleton"][70:80, IDX["l_ankle"]])
    assert err.max() < 0.05
    assert (out["body_height"] > 0).all()
