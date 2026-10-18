"""ISU base values (approximate).

!!! NEEDS CHECKING against the ISU Scale of Values (SOV) for the seasons in FineFS
(2018-19 .. 2021-22, ISU Communication 2168 / 2253 / 2363 etc.) and the current SOV
if you predict on new data. Values below are from memory of the 2018-19+ SOV and may be
off by small amounts for some spins / levels. Rules encoded (2018-2022 era):
  - under-rotated (<): 80% of BV; downgraded (<<): BV of one rotation fewer; q: full BV
  - wrong edge (e): 80% of BV ("!" is GOE-only)
  - e and < together: 60% of BV (approximation of SOV "e<" column)
  - jump sequence (+SEQ): 80% of summed BV (pre-2022-23 rule)
  - +REP: 70% of BV
  - bonus x: x1.1 for jumps in the 2nd half (SP: last jump element, FS: last three jump elements)
  - invalid (*): 0
Spins with "V": ~75% of the level value (approximation).
"""
from __future__ import annotations

from typing import Dict, Optional

from ..data.elements import Element, Jump

JUMP_BV: Dict[str, Dict[int, float]] = {
    # rotations: 1, 2, 3, 4
    "T": {1: 0.40, 2: 1.30, 3: 4.20, 4: 9.50},
    "S": {1: 0.40, 2: 1.30, 3: 4.30, 4: 9.70},
    "Lo": {1: 0.50, 2: 1.70, 3: 4.90, 4: 10.50},
    "F": {1: 0.50, 2: 1.80, 3: 5.30, 4: 11.00},
    "Lz": {1: 0.60, 2: 2.10, 3: 5.90, 4: 11.50},
    "A": {1: 1.10, 2: 3.30, 3: 8.00, 4: 12.50},
}
EULER_BV = 0.50

# level -> BV; keys "B", "1".."4"
SPIN_BV: Dict[str, Dict[str, float]] = {
    "USp": {"B": 1.0, "1": 1.2, "2": 1.5, "3": 1.9, "4": 2.4},
    "LSp": {"B": 1.2, "1": 1.5, "2": 1.9, "3": 2.4, "4": 2.7},
    "CSp": {"B": 1.1, "1": 1.3, "2": 1.6, "3": 2.1, "4": 2.6},
    "SSp": {"B": 1.1, "1": 1.3, "2": 1.6, "3": 2.1, "4": 2.5},
    "FUSp": {"B": 1.5, "1": 1.7, "2": 2.0, "3": 2.4, "4": 2.9},
    "FLSp": {"B": 1.7, "1": 2.0, "2": 2.4, "3": 2.9, "4": 3.2},
    "FCSp": {"B": 1.6, "1": 1.9, "2": 2.3, "3": 2.8, "4": 3.2},
    "FSSp": {"B": 1.7, "1": 2.0, "2": 2.3, "3": 2.6, "4": 3.0},
    "CUSp": {"B": 1.5, "1": 1.8, "2": 2.0, "3": 2.4, "4": 2.9},
    "CLSp": {"B": 1.7, "1": 2.0, "2": 2.4, "3": 2.9, "4": 3.2},
    "CCSp": {"B": 1.7, "1": 2.0, "2": 2.3, "3": 2.8, "4": 3.2},
    "CSSp": {"B": 1.6, "1": 1.9, "2": 2.3, "3": 2.6, "4": 3.0},
    "FCUSp": {"B": 1.5, "1": 1.8, "2": 2.0, "3": 2.4, "4": 2.9},
    "FCLSp": {"B": 1.7, "1": 2.0, "2": 2.4, "3": 2.9, "4": 3.2},
    "FCCSp": {"B": 1.7, "1": 2.0, "2": 2.3, "3": 2.8, "4": 3.2},
    "FCSSp": {"B": 1.6, "1": 1.9, "2": 2.3, "3": 2.6, "4": 3.0},
    "CoSp": {"B": 1.5, "1": 1.7, "2": 2.0, "3": 2.5, "4": 3.0},
    "CCoSp": {"B": 1.7, "1": 2.0, "2": 2.5, "3": 3.0, "4": 3.5},
    "FCoSp": {"B": 1.7, "1": 2.0, "2": 2.5, "3": 3.0, "4": 3.5},
    "FCCoSp": {"B": 1.7, "1": 2.0, "2": 2.5, "3": 3.0, "4": 3.5},
}
STEP_BV: Dict[str, Dict[str, float]] = {
    "StSq": {"B": 1.5, "1": 1.8, "2": 2.6, "3": 3.3, "4": 3.9},
    "ChSq": {"B": 3.0, "1": 3.0, "2": 3.0, "3": 3.0, "4": 3.0},
}
SPIN_V_FACTOR = 0.75

# Fallbacks used at inference when the model does not predict spin/step levels. These are
# overwritten by training-set means (stored in the checkpoint as `bv_priors`).
DEFAULT_PRIORS = {"spin": 3.0, "step": 3.5}


def jump_bv(j: Jump) -> float:
    if j.invalid or j.rotations <= 0:
        return 0.0
    if j.euler:
        return EULER_BV
    rot = min(j.rotations, 4)
    if j.ur == "<<":
        rot -= 1
        if rot <= 0:
            return 0.0
    bv = JUMP_BV[j.type][rot]
    factor = 1.0
    if j.ur == "<":
        factor *= 0.8
    if j.edge == "e":
        factor = 0.6 if j.ur == "<" else 0.8 * factor
    return bv * factor


def element_bv(el: Element, bonus: Optional[bool] = None, priors: Optional[Dict[str, float]] = None) -> float:
    """Base value of a parsed element. `bonus` overrides el.bonus (x1.1, jumps only)."""
    if el.invalid:
        return 0.0
    if el.kind == "jump":
        total = sum(jump_bv(j) for j in el.jumps)
        if el.comb in (3, 4):
            total *= 0.8
        if el.rep:
            total *= 0.7
        if el.bonus if bonus is None else bonus:
            total *= 1.1
        return round(total, 2)
    table = SPIN_BV if el.kind == "spin" else STEP_BV if el.kind == "step" else None
    if table is not None and el.spin_code in table and el.level in table[el.spin_code]:
        v = table[el.spin_code][el.level]
        if el.v_reduced:
            v *= SPIN_V_FACTOR
        return round(v, 2)
    pri = priors or DEFAULT_PRIORS
    return float(pri.get(el.kind, 0.0))


def bonus_flags(program_type: str, kinds: list) -> list:
    """Apply the 2018-2022 bonus rule: SP -> last jump element, FS -> last three jump elements."""
    n_bonus = 1 if program_type == "sp" else 3
    flags = [False] * len(kinds)
    jump_idx = [i for i, k in enumerate(kinds) if k == "jump"]
    for i in jump_idx[-n_bonus:]:
        flags[i] = True
    return flags
