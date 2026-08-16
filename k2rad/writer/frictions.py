"""Starter friction tables: *DEFINE_FRICTION -> /FRICTION.

One module rather than a block inside ``contacts.py`` because /FRICTION is a
standalone entity with its own id space (the LS-DYNA table id, preserved 1:1)
and its own reader (``starter/source/interfaces/friction/reader/
hm_read_friction.F``); the contacts only reference it through the ``fric_ID``
column, which is plumbed from ``contacts.py``.
"""

from __future__ import annotations

from typing import Dict, List, Set

from ..state import ConversionState, DefineFriction, FrictionPair
from .common import HDR, _emit_grpart_part, _f, _i

__all__ = [
    "_FRICTION_IFRIC_DARMSTAD",
    "_FRICTION_IFORM_STIFFNESS",
    "_friction_coeffs",
    "_make_frictions",
]


#: /FRICTION Ifric = 2, the "Darmstad law"
#: (``hm_read_friction.F`` FORMAT 3506; engine ``i7for3.F:1911-1914``)::
#:
#:     XMU = Fric + C1*e^(C2*v)*p^2 + C3*e^(C4*v)*p + C5*e^(C6*v)
#:
#: With C1..C4 = 0 this collapses to ``Fric + C5*e^(C6*v)``, which reproduces
#: LS-DYNA's ``mu_c = FD + (FS - FD)*e^(-DC*|v_rel|)`` EXACTLY for
#: ``Fric = FD``, ``C5 = FS - FD``, ``C6 = -DC``. That is dyna2rad's mapping
#: (``convertfrictions.cxx:64, 94-97``) and the only 2022-legal one: Radioss's
#: own exponential-decay law Ifric=4 needs one fewer sign flip but does not
#: exist before radioss2023 (``radioss2020/FRICTION/friction.cfg:87-93`` offers
#: 0-3, and the 2022 Reference Guide p.223 lists only 0-3), so emitting it from
#: a /BEGIN 2022 deck would be the WARNING-100211 kind of forward reference.
_FRICTION_IFRIC_DARMSTAD = 2

#: /FRICTION Iform = 2, "stiffness (incremental) formulation" — dyna2rad writes
#: it on every table (``convertfrictions.cxx:65``). Note the side effect in
#: ``hm_read_friction.F:182``: ``IF (FRICFORM==2) VISCF=ZERO``, i.e. the
#: starter zeroes VIS_f whenever Iform=2. See _make_frictions for why VC is
#: written anyway.
_FRICTION_IFORM_STIFFNESS = 2


def _friction_coeffs(fs: float, fd: float, dc: float):
    """(Fric, C5, C6) for one LS-DYNA (FS, FD, DC) triple — see
    _FRICTION_IFRIC_DARMSTAD for the algebra.

    ``C6`` is left at 0 when DC is 0 (dyna2rad ``convertfrictions.cxx:92-93``
    guards the assignment the same way): with C6=0 the decay term is the
    constant ``C5``, so ``mu = FD + (FS - FD) = FS`` at every sliding speed —
    which is exactly what LS-DYNA's law degenerates to for DC=0.
    """
    return fd, fs - fd, (-dc if dc != 0.0 else 0.0)


def _friction_pair_lines(state: ConversionState, fric: DefineFriction,
                         pair: FrictionPair, grpart_ids: Dict[int, int],
                         out_lines: List[str]) -> List[str]:
    """The three-card block for one part pair, or [] when a side is unusable."""
    ids = []
    for pid, is_set in ((pair.pid_i, pair.pset_i), (pair.pid_j, pair.pset_j)):
        if is_set:
            if pid not in state.part_sets:
                state.warn(
                    f"*DEFINE_FRICTION {fric.fric_id}: part-pair row names "
                    f"*SET_PART {pid} (PTYPE=PSET), which does not exist in "
                    "this deck — the row is DROPPED and that pair falls back "
                    "to the table's default coefficients. (LS-DYNA calls this "
                    "an error unless ICNEP=1.)")
                return []
            if pid not in grpart_ids:
                gid = state.next_id()
                grpart_ids[pid] = gid
                out_lines += _emit_grpart_part(
                    gid, f"friction_{fric.fric_id}_pset_{pid}",
                    sorted(state.part_sets[pid][1]))
            ids.append((grpart_ids[pid], 0))
        else:
            if pid not in state.parts:
                state.warn(
                    f"*DEFINE_FRICTION {fric.fric_id}: part-pair row names "
                    f"part {pid}, which does not exist in this deck — the row "
                    "is DROPPED and that pair falls back to the table's "
                    "default coefficients. (LS-DYNA calls this an error unless "
                    "ICNEP=1.)")
                return []
            ids.append((0, pid))
    (grp1, part1), (grp2, part2) = ids
    p_fric, p_c5, p_c6 = _friction_coeffs(pair.fs, pair.fd, pair.dc)
    return [
        "#grpartID1 grpartID2   partID1   partID2                IDIR",
        f"{_i(grp1)}{_i(grp2)}{_i(part1)}{_i(part2)}                    0",
        "#            C1_DIR1             C2_DIR1             C3_DIR1"
        "             C4_DIR1             C5_DIR1",
        f"                   0                   0                   0"
        f"                   0{_f(p_c5)}",
        "#            C6_DIR1           FRIC_DIR1          VIS_F_DIR1",
        f"{_f(p_c6)}{_f(p_fric)}{_f(pair.vc)}",
    ]


def _make_frictions(state: ConversionState) -> List[str]:
    """*DEFINE_FRICTION -> /FRICTION (see :class:`~k2rad.state.DefineFriction`).

    Card layout, ``radioss2020/FRICTION/friction.cfg:265-294`` — the newest
    FORMAT at or below /BEGIN 2022, and byte-identical to the 2023/2024 ones::

        /FRICTION/fric_ID
        title
        #   I_fric   I_filtr              X_freq    I_form     %10d%10d%20lg%10d
        #        C1        C2        C3        C4        C5     5 x %20lg
        #        C6      FRIC     VIS_f                         3 x %20lg
        (per pair, free-form, terminated by the next / keyword)
        #grpartID1 grpartID2   partID1   partID2      IDIR
                                       %10d%10d%10d%10d + 10 literal blanks + %10d
        #   C1_DIR1 .. C5_DIR1                        5 x %20lg
        #   C6_DIR1  FRIC_DIR1  VIS_F_DIR1            3 x %20lg

    The header row is not decoration: the engine SEEDS every contact pair from
    it (``frictionparts_model.F:88-92`` copies ``TABCOEF_FRIC(1)`` into
    ``FRICC`` and ``TABCOEF_FRIC(J+2)`` into ``FRIC_COEFS(:,J)``) and a
    part-pair row only overrides where a pair matches — so LS-DYNA's default
    row (FS_D/FD_D/DC_D) has to land there, not on the interface card.

    Rows are emitted in deck order, un-expanded and un-deduplicated, exactly as
    dyna2rad does (``convertfrictions.cxx:107-184``). ``Idir`` is always 0
    (isotropic): *DEFINE_FRICTION_ORIENTATION, which is what would make it 1,
    is a separate keyword that neither converter handles.
    """
    if not state.define_frictions:
        return []
    lines = ["#-  FRICTION TABLES (*DEFINE_FRICTION -> /FRICTION):", HDR]
    #: *SET_PART id → the /GRPART/PART emitted for it, so a set referenced by
    #: several rows (or several tables) gets exactly one group.
    grpart_ids: Dict[int, int] = {}
    warned_vc: Set[int] = set()

    for fric in state.define_frictions.values():
        d_fric, d_c5, d_c6 = _friction_coeffs(fric.fs, fric.fd, fric.dc)
        pair_lines: List[str] = []
        pre_lines: List[str] = []      # /GRPART groups the rows need
        n_rows = 0
        for pair in fric.pairs:
            block = _friction_pair_lines(state, fric, pair, grpart_ids,
                                         pre_lines)
            if block:
                pair_lines += block
                n_rows += 1
        lines += pre_lines
        lines += [
            f"/FRICTION/{fric.fric_id}",
            fric.title or f"FRICTION_{fric.fric_id}",
            "#   I_fric   I_filtr              X_freq    I_form",
            f"{_i(_FRICTION_IFRIC_DARMSTAD)}         0                   0"
            f"{_i(_FRICTION_IFORM_STIFFNESS)}",
            "#                 C1                  C2                  C3"
            "                  C4                  C5",
            f"                   0                   0                   0"
            f"                   0{_f(d_c5)}",
            "#                 C6                FRIC               VIS_f",
            f"{_f(d_c6)}{_f(d_fric)}{_f(fric.vc)}",
        ]
        lines += pair_lines
        lines.append(HDR)

        state.warn(
            f"*DEFINE_FRICTION {fric.fric_id} -> /FRICTION/{fric.fric_id} "
            f"(Ifric=2 Darmstad, Iform=2, {n_rows} part-pair row(s) + the "
            "default row). LS-DYNA's mu = FD + (FS-FD)*exp(-DC*|v|) maps EXACTLY "
            f"onto Fric={d_fric:g}, C5=FS-FD={d_c5:g}, C6=-DC={d_c6:g} with "
            "C1..C4=0 (engine i7for3.F:1911-1914). Bind it to a contact with "
            "*CONTACT Card-2 FS=-2; an interface with fric_ID set ignores its "
            "own Fric/Ifric entirely (2022 Reference Guide p.268 remark 16).")
        if fric.icnep:
            state.warn(
                f"*DEFINE_FRICTION {fric.fric_id}: ICNEP={fric.icnep} "
                "('ignore rows naming a non-existent part') has no /FRICTION "
                "field — k2rad drops such a row and warns either way, so the "
                "behaviour already matches ICNEP=1.")
        vc_values = [fric.vc] + [p.vc for p in fric.pairs]
        if any(v != 0.0 for v in vc_values) and fric.fric_id not in warned_vc:
            warned_vc.add(fric.fric_id)
            state.warn(
                f"*DEFINE_FRICTION {fric.fric_id}: the VC column is written to "
                "/FRICTION VIS_f (as dyna2rad does), but the two are NOT the "
                "same quantity — LS-DYNA VC is a viscous friction STRESS CAP "
                "(F_lim = VC * A_contact, Vol I p.17-280) while Radioss VIS_f "
                "is a friction critical-damping coefficient. On top of that the "
                "starter zeroes it for Iform=2 (hm_read_friction.F:182 "
                "'IF (FRICFORM==2) VISCF=ZERO') and the engine zeroes friction "
                "damping for NTY 24/25 regardless (frictionparts_model.F:"
                "108-112). Treat the shear-stress cap as NOT converted.")
        if not fric.pairs:
            state.warn(
                f"*DEFINE_FRICTION {fric.fric_id} has no part-pair rows — the "
                "table is emitted with only its default row, which applies to "
                "every contact pair. That is legal, but if the deck meant to "
                "give specific part pairs their own coefficients, check that "
                "the Card-2 rows survived the *INCLUDE / free-format parse.")
    return lines
