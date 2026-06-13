"""
k2rad  –  LS-DYNA .k → OpenRadioss .rad converter.

Usage::

    from k2rad import convert
    result = convert("model.k")
    print(result.starter_path, result.engine_path)
    for w in result.warnings:
        print("WARNING:", w)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .parser import parse_k_file
from .handlers import dispatch
from .state import ConversionState, ContactAutoSingle, ConvertOptions
from .writer import build_starter, build_engine, _warn_implicit_solid_contact_np1


def _inject_implicit_contact_stub(state: ConversionState) -> None:
    """Work around an OpenRadioss engine crash.

    The OpenRadioss implicit solver segfaults during setup (before
    ``IMPLICIT OPTION USED`` is even printed) when the model defines **no**
    contact interface — even though a part loaded only by boundary conditions
    or forces is a perfectly valid implicit problem.  A model *with* at least
    one ``/INTER`` runs fine.

    So when converting an implicit model that has no contact, inject one inert
    all-parts self-contact (``/INTER/TYPE7``).  On a model whose parts never
    touch it transmits no load, so results are unchanged — it merely gives the
    engine the interface its implicit setup requires.
    """
    if not state.is_implicit:
        return
    if state.contacts_single or state.contacts_surf2surf:
        return
    if not (state.solid_elems or state.shell_elems):
        return  # no deformable surface to build the interface from
    inter_id = state.next_id()
    state.contacts_single.append(
        ContactAutoSingle(
            inter_id=inter_id,
            title="auto_implicit_stabilization_self_contact",
            ssid=0, sstyp=0, fs=0.0, fd=0.0, bt=0.0, dt=1.0e28,
        )
    )
    state.warn(
        "Implicit model has no contact interface — the OpenRadioss engine "
        "segfaults in implicit setup without one. Injected an inert all-parts "
        f"self-contact (/INTER/TYPE7 id {inter_id}); it carries no load unless "
        "parts actually touch. Remove it if you define real contact."
    )


@dataclass
class ConversionResult:
    starter_path: str
    engine_path: str
    warnings: List[str]
    skipped_keywords: List[str]


def convert(
    input_path: str,
    output_stem: Optional[str] = None,
    units: tuple = ("Mg", "mm", "s"),
    *,
    ground_springs: bool = False,
    ground_spring_k: float = 100.0,
    inter_gapmin: Optional[Dict[int, float]] = None,
    soften_stfac: Optional[float] = None,
) -> ConversionResult:
    """Convert a LS-DYNA .k file to OpenRadioss Starter + Engine .rad files.

    Parameters
    ----------
    input_path : str
        Path to the LS-DYNA keyword file (.k).
    output_stem : str, optional
        Base path for output files (without ``_0000.rad`` / ``_0001.rad``).
        Defaults to *input_path* with the extension removed.
    units : tuple of (mass, length, time)
        Unit strings written to the /BEGIN header.  Defaults to the LS-DYNA
        ton-mm-s system ("Mg", "mm", "s").  This only labels the header — the
        converter never rescales numeric values, so the labels should match
        the units already used in the .k file.

    Other Parameters
    ----------------
    ground_springs : bool
        Inject soft /PROP/TYPE8 grounding springs on every force-loaded rigid
        body to bootstrap the singular t=0 tangent of force control through a
        clearance-fit contact. Off by default.
    ground_spring_k : float
        Grounding-spring stiffness (N/mm) per loaded axis. Default 100.
    inter_gapmin : dict[int, float], optional
        Per-interface Gapmin overrides ``{inter_id: gapmin}`` applied to the
        emitted /INTER/TYPE7 (drops a pulled interface's pre-penetration).
    soften_stfac : float, optional
        Stfac (penalty stiffness scale) set on ALL /INTER/TYPE7 interfaces
        (e.g. 0.3). None leaves the engine default (0).

    All four are opt-in: with their defaults the output is byte-identical to a
    plain conversion (see :class:`~k2rad.state.ConvertOptions`).

    Returns
    -------
    ConversionResult
        Paths of the two generated files plus any warnings.
    """
    input_path = str(input_path)
    if output_stem is None:
        stem = Path(input_path).with_suffix("")
        output_stem = str(stem)

    starter_path = output_stem + "_0000.rad"
    engine_path  = output_stem + "_0001.rad"

    # 1. Parse
    blocks = parse_k_file(input_path)

    # 2. Dispatch each block to fill state
    state = ConversionState()
    state.units = tuple(units)
    state.options = ConvertOptions(
        ground_springs=ground_springs,
        ground_spring_k=ground_spring_k,
        inter_gapmin=dict(inter_gapmin or {}),
        soften_stfac=soften_stfac,
    )
    for block in blocks:
        dispatch(block, state)

    # 2b. Implicit safety net: a contact-free implicit model segfaults the
    #     OpenRadioss engine during setup, so give it one inert self-contact.
    _inject_implicit_contact_stub(state)

    # 2c. Implicit np>1 limitation: a solid-part contact surface makes the
    #     OpenRadioss SPMD engine segfault at the first implicit solve. The
    #     converter cannot rewrite the deck around it (it is not a surface bug),
    #     so warn the user to run np=1.
    _warn_implicit_solid_contact_np1(state)

    # 3. Generate output text
    starter_text = build_starter(state)
    engine_text  = build_engine(state)

    # 4. Write files
    with open(starter_path, "w", newline="\n") as fh:
        fh.write(starter_text)
    with open(engine_path, "w", newline="\n") as fh:
        fh.write(engine_text)

    return ConversionResult(
        starter_path=starter_path,
        engine_path=engine_path,
        warnings=list(state.warnings),
        skipped_keywords=sorted(set(state.skipped_keywords)),
    )


__all__ = ["convert", "ConversionResult"]
