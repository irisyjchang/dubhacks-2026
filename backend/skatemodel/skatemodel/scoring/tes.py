"""TES = sum over elements of (ISU base value lookup + predicted GOE)."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from ..data.dataset import SEG_CLASSES
from ..data.elements import COMB_CLASSES, JUMP_TYPES, UR_CLASSES, Element, Jump, format_element, parse_element
from .base_values import DEFAULT_PRIORS, bonus_flags, element_bv

N_JUMPS_FOR_COMB = {0: 1, 1: 2, 2: 3, 3: 2, 4: 3}


def _class_kind(code: str) -> str:
    return "spin" if "Sp" in code else "step" if "Sq" in code else "jump"


def decode_element(kind: str, head: Dict[str, np.ndarray], i: int,
                   class_codes: Optional[List[str]] = None) -> Element:
    """Build an Element from element-head outputs. If a dataset class head (e.g. MMFS-63) exists,
    its best class consistent with the segment kind gives the code (incl. spin/step levels)."""
    if class_codes is not None and "eclass" in head:
        logits = head["eclass"][i].copy()
        same = np.array([_class_kind(c) == kind for c in class_codes])
        if same.any():
            logits[~same] = -np.inf
        code = class_codes[int(np.argmax(logits))]
        el = parse_element(code, coarse_class=kind)
        el.fall = bool(head["fall"][i] > 0.0)
        return el
    el = Element(code="", kind=kind)
    if kind == "jump":
        comb = int(np.argmax(head["comb"][i]))
        el.comb = comb
        for k in range(N_JUMPS_FOR_COMB[comb]):
            el.jumps.append(Jump(type=JUMP_TYPES[int(np.argmax(head["jtype"][i, k]))],
                                 rotations=int(np.argmax(head["rot"][i, k])) + 1,
                                 ur=UR_CLASSES[int(np.argmax(head["ur"][i, k]))]))
    el.fall = bool(head["fall"][i] > 0.0)  # logit > 0
    el.code = format_element(el) if kind == "jump" else kind
    return el


def score_program(kinds: List[str], head: Dict[str, np.ndarray], program_type: str,
                  priors: Optional[Dict[str, float]] = None, class_codes: Optional[List[str]] = None) -> Dict:
    """kinds: element kinds in temporal order; head: element-head outputs for those segments."""
    priors = priors or DEFAULT_PRIORS
    bonus = bonus_flags(program_type, kinds)
    elements, tes = [], 0.0
    for i, kind in enumerate(kinds):
        el = decode_element(kind, head, i, class_codes)
        bv = element_bv(el, bonus=bonus[i], priors=priors)
        goe = float(np.clip(head["grade"][i], -5, 5)) / 10.0 * bv
        tes += bv + goe
        elements.append({"code": el.code, "kind": kind, "bv": round(bv, 2), "goe": round(goe, 2),
                         "fall": el.fall, "bonus": bonus[i]})
    return {"tes": float(tes), "elements": elements}


__all__ = ["score_program", "decode_element", "SEG_CLASSES", "COMB_CLASSES"]
