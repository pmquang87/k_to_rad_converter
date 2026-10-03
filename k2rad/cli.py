#!/usr/bin/env python3
"""
k2rad.cli  –  command-line entry point for the LS-DYNA .k → OpenRadioss .rad
converter.

Installed as the ``k2rad`` console script (see pyproject.toml), and also driven
by the repo-root ``k2rad.py`` shim so ``python k2rad.py model.k`` keeps working
from a checkout without installing anything.

Examples
--------
    k2rad model.k
    k2rad model.k output/model
    k2rad model.k --units Mg mm s
"""

import argparse
import sys
from pathlib import Path
from typing import Union


def _tie_stfac_arg(text: str) -> Union[str, float]:
    """``--tie-stfac`` accepts a number or the literal ``auto``.

    ``auto`` is kept as the STRING all the way to the writer, which is the only
    place that can evaluate ``100*3(1-2nu)`` — nu comes from the tie's own main
    side, so there is no one value the CLI could resolve it to.
    """
    if text.strip().lower() == "auto":
        return "auto"
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--tie-stfac takes a number or 'auto', not {text!r}")


def _qstat_dtscal_arg(text: str) -> Union[str, float]:
    """``--qstat-dtscal`` accepts a positive number or the literal ``none``.

    ``none`` is kept as the STRING all the way to the writer, where it means
    "emit no ``/IMPL/QSTAT`` card at all" — which is Radioss's own default
    (``SCAL_DTQ = 1``, ``freimpl.F:135``) and is measured WORSE than 10 on this
    corpus, so it is an escape rather than a value.
    """
    if text.strip().lower() == "none":
        return "none"
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--qstat-dtscal takes a number or 'none', not {text!r}")
    if v <= 0.0:
        raise argparse.ArgumentTypeError(
            "--qstat-dtscal must be > 0 (use 'none' to emit no /IMPL/QSTAT "
            "card)")
    return v


def _make_progress_printer():
    """A convert() progress callback that prints an updating percentage line."""
    def cb(frac: float, label: str) -> None:
        pct = int(frac * 100)
        sys.stdout.write(f"\r  [{pct:3d}%] {label:<36}")
        sys.stdout.flush()
        if frac >= 1.0:
            sys.stdout.write("\n")
    return cb


def _print_gapmin_suggestions(input_path: str, factor: float, analyze_file) -> int:
    """Report suggested per-interface Gapmins for *input_path* (read-only)."""
    from .gapmin import fast_proximity_available

    print(f"Analyzing node-to-segment contact clearances: {input_path}")
    if not fast_proximity_available():
        print("  NOTE: numpy + scipy are not installed, so the node-to-segment")
        print("        clearance cannot be measured and no Gapmin can be suggested.")
        print("        Install them:  pip install scipy   (see docs/DEPENDENCIES.md)")
    suggestions, skipped = analyze_file(input_path, factor)
    if not suggestions and not skipped:
        print("  No contact interfaces found.")
        return 0
    if suggestions:
        print(f"\n  Suggested Gapmin (= {factor:g} x node-to-segment clearance):")
        for iid in sorted(suggestions):
            s = suggestions[iid]
            print(f"    INTER {iid} ({s.title}): {s.side_a} -> {s.side_b}")
            print(f"        node-to-segment clearance = {s.min_distance:g}  ->  Gapmin = {s.suggested_gapmin:g}")
        print(f"\n  Apply with:  --auto-gapmin --gapmin-factor {factor:g}")
        print("  Or pin explicitly:  " + " ".join(
            f"--inter-gapmin {i}={suggestions[i].suggested_gapmin:g}" for i in sorted(suggestions)))
    if skipped:
        print("\n  No suggestion (set manually if needed):")
        for iid in sorted(skipped):
            print(f"    INTER {iid}: {skipped[iid]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser (split out for testing)."""
    parser = argparse.ArgumentParser(
        prog="k2rad",
        description="Convert a LS-DYNA .k keyword file to OpenRadioss .rad format.",
    )
    parser.add_argument(
        "input",
        help="Path to LS-DYNA keyword file (.k)",
    )
    parser.add_argument(
        "output_stem",
        nargs="?",
        default=None,
        help="Output stem (default: same directory/name as input, without extension). "
             "Files written as <stem>_0000.rad and <stem>_0001.rad.",
    )
    parser.add_argument(
        "--units",
        nargs=3,
        metavar=("MASS", "LENGTH", "TIME"),
        default=("Mg", "mm", "s"),
        help="Unit labels for the /BEGIN header (default: Mg mm s). "
             "Labels only — values are never rescaled.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress warnings and skip-summary output",
    )
    parser.add_argument(
        "--tet10-to-tet4",
        action="store_true",
        help="Downgrade every 10-node quadratic tet to a 4-node linear tet (keep "
             "the 4 corners, drop the mid-edge nodes). Use when only a TET10 .k is "
             "available but a TET4 run is wanted. Linear tets are stiffer/less "
             "accurate — remesh for production accuracy.",
    )
    parser.add_argument(
        "--fixpoint-count",
        type=int,
        default=0,
        metavar="N",
        help="Number of evenly spaced /IMPL/DT/FIXPOINT output milestones the "
             "implicit time-step controller is forced to land on (k/N x the run "
             "end, for k = 1..N). Clamped to the engine's 1..100 range. "
             "DEFAULT 0 = no card, changed 2026-09 from 100: the grid makes "
             "the adaptive step oscillate hard against /IMPL/DT/2 (ex_14's own "
             "cycle table alternates a big FIXPOINT jump with a tiny recovery "
             "at 2:1 ratios), and trapezoidal Newmark is unconditionally "
             "stable at a CONSTANT step, not at one that alternates like "
             "that. MEASURED on the dynaexamples R14 roster: ten decks that "
             "died 'SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT' reach "
             "NORMAL TERMINATION without it (ex_01 x3, ex_14 x4, ex_15 x3 - "
             "ex_01_thin_shell_elform_2 from an ERROR at t = 0.105 to t = "
             "1.000 at IE -14.12 %% against its LS-DYNA reference - the "
             "COMBINED arm, re-measured after --qstat-dtscal 10 reached the "
             "same deck's _0001.rad; the -13.7 %% this string used to quote "
             "was the DTSCAL-0.1 arm; "
             "ex_14_solid_elform_1 from ERROR TERMINATION to NORMAL at cycle "
             "33, t = 0.01839 of 0.02, engine energy error -0.7 %%, IE "
             "5.044e7 / KE 4.974e7 against the LS reference's 2.4162e7 / "
             "3.937e7 - the -3.1 %% / 1.417e7 / 3.231e7 this string used to "
             "quote is the --no-default-hourglass arm of the same deck, not "
             "this one), 4.2_Buckling_of_Beer_Can "
             "reaches 2.8x further, and three currently-NORMAL controls do "
             "not regress (two improve). A COARSER grid is not the fix: at "
             "--fixpoint-count 10 ex_15 terminates at a 99.9 %% energy error "
             "and ex_14 at 86.1 %%, both NORMAL banners over junk. "
             "The COST of 0 is fewer output states - 15 "
             "cycles become 8 on the controls - which is the whole reason the "
             "card exists, so pass a count back if you need the milestones. "
             "Implicit decks only; ignored for explicit.",
    )

    parser.add_argument(
        "--qstat-dtscal",
        type=_qstat_dtscal_arg,
        default=10.0,
        metavar="VALUE|none",
        help="The /IMPL/QSTAT/DTSCAL inertia-stabilization scale on a "
             "QUASI-STATIC implicit deck (one with no "
             "*CONTROL_IMPLICIT_DYNAMICS). Default 10. The stabilization "
             "added to the stiffness diagonal is "
             "M/((1+alpha)*beta*(DTSCAL*dt)^2) (imp_dyna.F:351-355), so it "
             "grows as 1/DTSCAL^2 AND as 1/dt^2: at the pre-2026-09 default "
             "of 0.1 it was 100x the Radioss default (SCAL_DTQ = 1, "
             "freimpl.F:135), and every auto-step cut made the tangent "
             "stiffer, shrinking the next Newton correction. LS-DYNA's "
             "standard static implicit adds none at all (its own d3hsp: "
             "'artificial stabilization flag 2 = off (standard analysis "
             "DEFAULT)'). MEASURED at nt 3 AND nt 4 against each deck's own "
             "LS-DYNA glstat: 4.2.frf.cant-1 goes from 4 cycles and an ERROR "
             "at 0.1 - the 4 is its pre-round campaign row; a quiet-machine "
             "master repeat never leaves cycle 0, and either way the arm "
             "advances nothing - to 104 cycles, t = 1.000, IE 7922 against the reference "
             "7946.31 (-0.31 %%) at 10; tensile2 +7.36 %%, "
             "6.5.tbl.psd.prepressure-1 +0.03 %%, doorbeam NORMAL. The COST "
             "is ex_02_thick_shell_elform_{2,3,5} (3 deck keys on ONE emitted "
             "file, all three not_comparable BOTH WAYS - because their LS "
             "reference KINETIC energy is a structural zero, which is what "
             "the rows' own note names; their LS IE 0.771729/0.058509/0.100376 "
             "is NOT a structural zero and IS the comparable channel, and it "
             "degrades 3.4/53.0/32.5 pp - so the VERDICT is unchanged but "
             "fidelity on that channel is not): the campaign rows read 1899 / "
             "1896 / 1903 cycles at 24.1 / 24.8 / 33.6 s NORMAL at 0.1 (nt 4) "
             "against a run still going at the 600 s campaign cap at 10, having "
             "reached t = 0.44 / 0.49 / 0.59 there and t = 0.32 on an "
             "independent quiet-machine repeat, at nt 3 AND nt 4 - the verdict "
             "does not flip with nt. That cost is the /PROP/TYPE20 card's, "
             "which k2rad wrote before round 7: the default "
             "--implicit-tshell-solid route now ends the family NORMAL in 28 "
             "cycles at this default (nt 4 and 2), and the value is inert "
             "there: 0.1 ends it in the same 28 cycles at the same IE "
             "(nt 4 and 2). Pass 0.1 to restore the old default on such a "
             "deck; on THAT family 0.1 together with "
             "--no-implicit-tshell-solid reproduces the pre-round-4 file "
             "BYTE FOR BYTE (both files; 0.1 alone does not since round "
             "7). 'none' emits no card "
             "at all - measured WORSE than either (ex_02 dies at cycle 0 and "
             "tensile2 at t = 0.746). --deformable-contact-recipe keeps its "
             "separately validated 0.05 and ignores this flag.",
    )
    parser.add_argument(
        "--arclength-riks",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Emit /IMPL/DT/3 (RIKS arc-length continuation) instead of "
             "/IMPL/DT/2 when *CONTROL_IMPLICIT_SOLUTION asks for LS-DYNA's "
             "arc-length method - THE MANUAL'S OWN RULE, Vol I R17 p.12-354 "
             "and p.12-358: 6 <= NSOLVR <= 9, or NSOLVR = 12 with card-3 "
             "ARCMTH = 3. (ARCCTL is NOT part of it: p.12-358 defines it as "
             "the arc-length CONTROLLING NODE ID whose 0 means 'generalized "
             "arc length method', and the whole card is ignored unless the "
             "method is already active. An ARCCTL != 0 clause shipped first "
             "and is retracted - it made ex_06_beam_elform_1 a carrier, and "
             "that deck's own LS-DYNA d3hsp shows plain BFGS.) Roster reach: "
             "2 keys, ex_05_beam_elform_3_&_6 and ex_07_beam_elform_1. "
             "OFF by default; the request is WARNED about "
             "either way. freimpl.F:384-387 reads seven fields "
             "(NL_DTP/ALEN0/NL_DTN/Tsca_dn/Tsca_up/IAL_M/SCAL_RIKS) and the "
             "zero cells take lectur.F:3518-3522's defaults. It buys the load "
             "path, not the answer: measured at nt 3 AND nt 4 on both "
             "carriers, error_engine either way, against this branch's own "
             "flag-off baseline: ex_07_beam_elform_1 walks from t = 0.3004 "
             "to t = 1.000 and lands "
             "at -1.72 %% of its LS-DYNA reference but still exits ERROR on "
             "the last increment; ex_05_beam_elform_3_&_6 fails in ~2 s "
             "without the flag and with it runs tens of thousands of cycles "
             "to t ~ 1e-7 and TIMES OUT. "
             "/IMPL/DT/FIXPOINT is deactivated by the engine under RIKS "
             "(lectur.F:3523-3532), so --fixpoint-count goes with it.",
    )
    parser.add_argument(
        "--zero-tolerance-ectol",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Give a *CONTROL_IMPLICIT_SOLUTION whose DCTOL/ECTOL/RCTOL are "
             "all 0 or blank LS-DYNA's own ECTOL default - /IMPL/NONLIN/1 "
             "Itol 1 (energy) Toli 0.01 - instead of k2rad's force default "
             "Itol 2. ON by default: LS-DYNA's own d3hsp echoes DCTOL 0.001 / "
             "ECTOL 0.01 on all 11 R14 decks of this shape (Vol I R17 "
             "p.12-354) - the rule rests on that echo, not on a measured "
             "gain. L_A is unchanged; a NEGATIVE cell is a tolerance "
             "curve (p.12-355) and keeps Itol 2. MEASURED (nt 4 = nt 2): the "
             "IE history is closer on 3 of the 11 carriers by at most 0.03 "
             "points of the reference peak and farther on 4; tensile2 ENDS at "
             "IE +7.36 %% -> "
             "-0.54 %% at 0.11x the cycles, but reads +53 %% at t 0.80 (+14 %% "
             "before), its history RMS 2.00 %% -> 2.48 %% of the reference "
             "peak; doorbeam +380.25 %% -> +582.00 %% (a named regression, "
             "larger mid-run); ie_shell ERROR -> NORMAL at IE -99.87 %% "
             "(status only). Use --no-zero-tolerance-ectol to keep Itol 2.",
    )
    parser.add_argument(
        "--constrained-global",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Convert *CONSTRAINED_GLOBAL (a global constraint plane, Vol I "
             "R17 p.10-38) to /BCS: the nodes within TOL of the plane (or "
             "1e-6 x the model extent when TOL is 0) get the row's TC/RC "
             "codes, UNIONED per node over all rows and with the deck's *NODE "
             "TC/RC cells, one /BCS per union code. ON by default; the "
             "selection equals LS-DYNA's own d3hsp spc summary on all 3 R14 "
             "carriers (305, 54, 24737 nodes). Use --no-constrained-global "
             "to leave those DOFs free.",
    )
    parser.add_argument(
        "--spotweld-node-synthesis",
        action="store_true",
        help="Give an ELFORM-9 *MAT_SPOTWELD beam that states ONE node its "
             "second one where Vol I R17 p.19-3 puts it - the given node "
             "moved onto the nearest reference segment of the tie that names "
             "the weld part, a new node on the nearest segment on the other "
             "side (spotweld.k: 1213 -> z 0, new node at z 2, length 2.0 = "
             "LS-DYNA's own d3plot and swforc). OFF by default: alone it only "
             "costs cycles (7.64x on spotweld.k, IE -99.92 %%); with "
             "--beam-contact-secondary the error changes sign, not size (IE "
             "-99.9 %% -> +82.0 %% at 7.80x the cycles) and the weld never "
             "fails (EFAIL has no /PROP/TYPE13 slot).",
    )
    parser.add_argument(
        "--beam-contact-secondary",
        action="store_true",
        help="Put the nodes of *ELEMENT_BEAM elements (beams, trusses, "
             "spotweld and discrete beams) of a part named on a contact side "
             "into that side's node group. OFF by default: it changes the "
             "secondary side of 4 R14 deck keys on 4 emitted models "
             "(spotweld.k, show-cases/contact-overview/main.k and the two "
             "Yaris giants) and of the two full-vehicle models in "
             "C:/openradioss_run (4489 / 5102 spotweld beams), none of which "
             "but spotweld.k has been run with it.",
    )
    parser.add_argument(
        "--implicit-constant-step",
        action="store_true",
        help="Cap the implicit step at the deck's own DT0 (/IMPL/DT/STOP "
             "DT_MAX := DT0) where LS-DYNA runs a CONSTANT step - an implicit "
             "deck stating IAUTO 0 or no *CONTROL_IMPLICIT_AUTO (Vol I R17 "
             "p.12-277), with 0 < DT0 < ENDTIM and no stated DTMAX <= DT0. "
             "OFF by default. Radioss keeps cutting a non-converged step "
             "(imp_dt.F:107-119) where LS-DYNA would stop; a pinned step "
             "ended 3 of 3 NORMAL quasi-static R14 decks in ERROR and is not "
             "offered. MEASURED (nt 4 = nt 2): ex_15 energy error +74.1 %% -> "
             "-0.9 %% at 3.81x the cycles (its end state at matched time: IE "
             "+36.2 %% -> -54.8 %%, KE +132.0 %% -> +0.5 %%; measured on the "
             "/PROP/TYPE20 card k2rad wrote before round 7 - the default "
             "--implicit-tshell-solid route closes ex_15's energy balance by "
             "itself, -0.7 %%, and on that routed card the cap takes ex_15 "
             "from 34 to 202 cycles (5.94x), energy error -0.7 %% -> -1.8 "
             "%%, end state IE +72.81 %% -> -55.94 %%, KE +27.37 %% -> "
             "+0.12 %%, history RMS IE 8.06 -> 3.19 / KE 9.52 -> 7.45 %% of "
             "the reference peak); ex_11 KE history "
             "error 16.07 %% -> 1.16 %% at 2.86x (at matched time KE +17.9 %% "
             "where the shipped run reads +1343 %% - both deviations, the "
             "engine never prints its last increment); with the default "
             "--zero-tolerance-ectol, tensile2 75 -> 168 cycles and IE "
             "-0.54 %% -> -4.36 %% at the END, but its IE history is the "
             "closest of the measured arms (RMS 2.48 %% -> 1.66 %% of the "
             "reference peak). Reaches 33 R14 deck keys on 22 emitted "
             "models.",
    )
    parser.add_argument(
        "--discrete-offset",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Honour *ELEMENT_DISCRETE's OFFSET cell (Vol I R17 p.19-33: 'a "
             "displacement or rotation at time zero ... a positive offset on "
             "a translational spring will lead to a tensile force being "
             "developed at time zero'). ON by default. Radioss spring "
             "deflection is purely geometric (r1def3.F:206) and /PROP/TYPE4 "
             "has no offset cell, so the exact restatement is "
             "f_RAD(d) = f_LS(d + OFFSET): the force function's ABSCISSAE are "
             "shifted by -OFFSET (ordinates untouched) and an /INISPRI/FULL "
             "carries the pre-stretch energy EI = 1/2*f_LS(OFFSET)*OFFSET. "
             "MEASURED on ex_17_spring_elform_0 and ex_18_spring_elform_0 "
             "(the only two carriers on 885 decks, both OFFSET 25.4) together "
             "with --spring-token-mass-compensation: IE +0.0074 %% / KE "
             "+0.039 %% and +0.0064 %% / -0.015 %% against their own LS-DYNA "
             "glstat, where the shipped arm was a strict ZERO model "
             "(-100 %% / -100 %%). The shift ALONE is +10.20 %% / -99.27 %% - "
             "the two halves are one change. Use --no-discrete-offset to go "
             "back to dropping the cell with a warning.",
    )
    parser.add_argument(
        "--spring-token-mass-compensation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Subtract k2rad's own artificial spring mass from the /ADMAS of "
             "the nodes it lands on. ON by default. LS-DYNA discrete elements "
             "are MASSLESS, but hm_read_prop04.F:136-142 refuses a "
             "/PROP/TYPE4 MASS <= 1e-15 (ERROR 229), so k2rad writes a token "
             "1e-4 and rinit3.F:1926/1937-1939 puts HALF of it on EACH end "
             "node, per element - a node touched by k springs carries "
             "k*1e-4/2 of invented mass. MEASURED ALONE it is inert "
             "(spring.k, spring1.k, gnonspring.k keep their cycle counts and "
             "their IE to four significant digits); it is load-bearing inside "
             "the --discrete-offset bundle, where it turns ex_17's +10.20 %% "
             "/ -99.27 %% into +0.0074 %% / +0.039 %% - uncompensated, the "
             "token shifts that deck's omega to 41.715 rad/s against LS-DYNA's "
             "43.954, a 5.4 %% frequency error. ROUND 5 extended it to the "
             "*CONSTRAINED_SPOTWELD weld tie and the two mass <= 0 fallbacks, "
             "and gave the class with NO /ADMAS to subtract from a NEGATIVE "
             "/ADMAS of its own (hm_read_admas.F:164-170 accepts one, WARNING "
             "ID 476): plates.nrbc's starter TOTAL MASS goes 2.0048E-04 -> "
             "1.0048E-04, LS-DYNA's own to every printed digit, at +1.21 %% cycles "
             "(2646 -> 2678, nt 4). It never writes a non-positive value on "
             "the deck's OWN /ADMAS, and it refuses a spring node that "
             "carries no mass of its own - no element mass and no "
             "*ELEMENT_MASS - because subtracting there would leave the node "
             "at EXACTLY MS = 0, which nothing catches (chkmsin.F:53 aborts "
             "only on MS < 0; accele.F:67-80 then freezes the node's "
             "velocity); a node with only an *ELEMENT_MASS (gnonspring: "
             "TOTAL MASS 1.02e-4 -> 2.0e-6 = LS-DYNA's) IS compensated.",
    )
    parser.add_argument(
        "--shell-to-solid-rbody",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Convert *CONSTRAINED_SHELL_TO_SOLID to one /RBODY per card (the "
             "shell node NID as the main node, the NSID set as the secondary "
             "group, Mass 0, ICoG 3, Ifail 0). ON by default. LS-DYNA names "
             "the substitute in the card's own Purpose sentence - \"Nodal "
             "rigid bodies can perform the same function and may also be "
             "used\", Vol I R17 p.10-182. THE COST: LS-DYNA lets the brick "
             "nodes \"move relative to each other in the fiber direction\" "
             "(p.10-183) and an /RBODY cannot, so the fibre can no longer "
             "stretch. MEASURED on constrained.shell_solid.dome (7 cards, 5 "
             "nodes each, nt 4): NORMAL 48190 cycles, EXT-WORK 1689 against "
             "LS-DYNA's 1692.55 (-0.21 %%), IE 0.6693 -> 873.9 (-99.90 %% -> "
             "+36.08 %%), KE 1.290e5 -> 806.4 (+12299.9 %% -> -22.49 %%) - "
             "the campaign row stays deviation. "
             "Use --no-shell-to-solid-rbody to go back to dropping the "
             "keyword.",
    )
    parser.add_argument(
        "--generalized-weld-butt",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Convert *CONSTRAINED_GENERALIZED_WELD_BUTT to one /RBODY per "
             "card with Ifail=1 and FN = FT = SIGY*L*D/BETA, expN = expT = 2. "
             "ON by default, COINCIDENT node pairs only. LS-DYNA's own model "
             "of this weld IS a nodal rigid body (\"When the failure time is "
             "reached the nodal rigid body becomes inactive\", Vol I R17 "
             "p.10-32) and its criterion beta*sqrt(sig_n^2 + 3*(tau_n^2 + "
             "tau_t^2)) >= sig_f maps onto rgbodv.F:267 with sig = F/(L*D). "
             "On a coincident pair Radioss's own normal is a ZERO vector "
             "(rgbodv.F:249-256), so FN is identically 0 and FT carries the "
             "whole reaction - hence FT = FNmax, not FNmax/sqrt(3), and a "
             "weld failing in pure SHEAR fails sqrt(3) late. EPSF, TFAIL, "
             "CID, FILTER, WINDOW, NPR and NPRT are dropped and named. "
             "MEASURED on constrained.butt-weld (nt 4): NORMAL 2082 cycles "
             "(+0.63 %%), IE -100.00 %% -> +4.70 %%, KE -30.79 %% -> "
             "-26.85 %%; the SAME two welds LS-DYNA's own .messag records "
             "trip the criterion at t 1.269e-3 against its 1.26914e-3 and are "
             "set off at 1.272e-3. Use "
             "--no-generalized-weld-butt to go back to dropping the keyword.",
    )
    parser.add_argument(
        "--initial-void-floor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="On a deck that states *INITIAL_VOID_PART/_SET on an ELFORM-12 "
             "part whose material is a *MAT_NULL + *EOS_* carrier, write "
             "Pmin = -1e-20 on the /MAT/HYD_VISC of that fluid (the void's "
             "own material and every LAW6 material of the deck's ELFORM-12 "
             "fluid). ON by default. NOT 0: hm_read_mat06.F:154 reads an "
             "exact Pmin 0 as -INFINITY, so the Pmin 0 every *MAT_NULL + "
             "*EOS_* /MAT/HYD_VISC carried was an UNBOUNDED tension in the "
             "cells the fluid leaves. "
             "A stated PC is overridden and named; refused on a deck with "
             "*ALE_MULTI-MATERIAL_GROUP (Vol I R17 p.28-134) and for a void "
             "that is not ELFORM 12 or not a LAW6 carrier. The void's low "
             "density is NOT written. MEASURED at nt 4: quadrature_B timeout "
             "-> NORMAL in 1095 cycles (IE +394.0 %%), bird_B timeout -> "
             "NORMAL in 2936 cycles (IE +1484.7 %%), bird-el NORMAL either "
             "way (IE +454.1 -> +1134.6 %%) - NORMAL, not a match: the void "
             "is still full of fluid. Use --no-initial-void-floor to fall "
             "back to the *MAT_NULL PC cell (--no-mat-null-pc-mu as well "
             "keeps Pmin 0).",
    )
    parser.add_argument(
        "--weld-exponents",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a failing *CONSTRAINED_SPOTWELD / "
             "*CONSTRAINED_GENERALIZED_WELD_SPOT weld's exponents N / M into "
             "its /PROP/TYPE13 as alpha1-3 = 1, beta1 = N, beta2 = beta3 = M "
             "when either differs from 2. ON by default. LS-DYNA fails the "
             "weld at (fn/SN)^N + (fs/SS)^M >= 1 (Vol I R17 p.10-213); a "
             "blank TYPE13 cell is read as alpha 1 / beta 2 "
             "(hm_read_prop13.F:1169-1170), so the blank card was always "
             "exponent 2. N = M = 2 writes nothing. Radioss sums the two shear "
             "directions where LS-DYNA uses the resultant: exact at M = 2 and "
             "for shear on one local axis; with both components present an "
             "M < 2 weld fails earlier than in LS-DYNA (conservative) and an "
             "M > 2 weld fails later (non-conservative). MEASURED at nt 4 on "
             "plates.nrbc / plates.spot "
             "(N = M = 1): rupture t 3.130e-4 (+29.4 %%) -> 2.460e-4 (+1.7 %% "
             "against LS-DYNA's 2.4193e-4), 0.899x the cycles, external work "
             "+60.66 -> +7.83 %%. Use --no-weld-exponents to leave the cells "
             "blank.",
    )
    parser.add_argument(
        "--constrained-linear",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Convert *CONSTRAINED_LINEAR_LOCAL / _GLOBAL (and the legacy "
             "*CONSTRAINED_LINEAR) to one /MPC per card: node = NID, Idof = "
             "DOF, skew = the /SKEW of CID, alpha = COEF. ON by default. The "
             "engine enforces sum(alpha_k v_k) = 0 by a Lagrange multiplier "
             "(lag_mpc.F) - LS-DYNA's equation with C0 = 0. Refused by name "
             "(the card stays skipped) on a DOF that also carries a /BCS or "
             "an imposed motion (WARNING 312), a rigid-body node, an "
             "element-free node, a zero COEF (hm_read_mpc.F:124 reads 0 as 1), "
             "DOF 7, an undefined CID, a (node, DOF) pair used twice. MEASURED "
             "on plates.lce (the only carrier): starter NUMMPC 1, 0 errors, "
             "engine identical to the base on all 683 rows. Use "
             "--no-constrained-linear to leave the card unconverted.",
    )
    parser.add_argument(
        "--shell-offset-gapmin",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="On a /INTER/TYPE7 whose main side is SOLID segments only and "
             "whose secondary is SHELLS that LS-DYNA offsets by half their "
             "thickness (the AUTOMATIC_* / SINGLE_SURFACE spellings always, "
             "Vol I R17 p.11-128/129; the others under *CONTROL_CONTACT "
             "SHLTHK 2, SHLTHK 1 on deformable shells, or their own Card B "
             "THKOPT 1), with no stated gap: write Gapmin = t/2 capped at "
             "0.5 x the smallest main-segment side, instead of the starter's "
             "derived 0.1 x that side (i7sti3.F:1055-1063). ON by default. "
             "Several thicknesses: written only when every t/2 is above the "
             "cap; a shell main is never touched. MEASURED on bend (t 0.381, "
             "SHLTHK 2, written the capped 0.127): IE -2.00 -> -1.42 %%, KE "
             "-68.65 -> -45.60 %% at matched time, 0.98x the cycles. Use "
             "--no-shell-offset-gapmin to keep the starter's derived gap.",
    )
    parser.add_argument(
        "--rigid-shell-rotary-inertia",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write J = -SUM(IN) into the Jxx/Jyy/Jzz cells of every "
             "*MAT_RIGID / *DEFORMABLE_TO_RIGID part /RBODY (ICoG != 4) whose "
             "nodes carry lumped shell rotary inertia: the starter ADDS every "
             "shell node's IN = (m/n)(A + t^2)/12 (cinmas.F:1379) to a rigid "
             "body's tensor (inirby.F:166-168, inirby.F:355-363), while "
             "LS-DYNA's rigid-part inertia is the point-mass sum (18 of 18 "
             "reference d3hsp tensors within 0.04 %%). ON by default. Skipped "
             "by name where the lumper is not the starter's (layered, element "
             "thickness, Ishell < 11, no section), refused by name below a "
             "relative 1e-6 margin (ERROR 274), never on CNRB / weld / tie / "
             "probe bodies. MEASURED (nt 4): a spun rigid plate's rotational "
             "KE +16.83 / +33.66 %% -> 0.00 %%; revo-stiff IE / KE history "
             "RMS 4.96 / 2.94 -> 0.78 / 0.73 %% of the LS peak at 1.156x "
             "the cycles, its LS d3hsp tensor 0.1977227E-02 reproduced. Use "
             "--no-rigid-shell-rotary-inertia to keep J = 0.",
    )
    parser.add_argument(
        "--spotweld-shear-yield",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Give the *MAT_SPOTWELD weld's /PROP/TYPE13 a bilinear SHEAR "
             "curve on Ty/Tz (fct_ID12 = fct_ID13, H2 = H3 = 1): yield "
             "(SIGY/sqrt3)·A, the von Mises shear yield of MAT_100's "
             "axial-and-shear plasticity (Vol II R17 p.2-708), hardening "
             "G·EH/(3G+EH)·A/L. ON by default. MEASURED on plates.mat100 "
             "(nt 4): LS-DYNA's weld shear plateaus at 20374..20408 = "
             "(SIGY/sqrt3)·A = 20405; IE / KE history RMS 23.53 / 62.56 -> "
             "8.58 / 26.74 %% of the LS peak at 1.107x the cycles. Named "
             "cost: mainboltaexpl (its preloaded bolt spring collapses "
             "either way). Use --no-spotweld-shear-yield to keep the shear "
             "elastic.",
    )
    parser.add_argument(
        "--spotweld-efail-displacement",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="A *MAT_SPOTWELD EFAIL (0 < EFAIL < 1e19) on a card with NO "
             "resultant failure cell -> /PROP/TYPE13 Ifail 1 / Ifail2 0 "
             "displacement failure, DeltaMax1 = delta_y + EFAIL·L, "
             "DeltaMax2,3 = delta_y,s + sqrt3·EFAIL·L (the effective plastic "
             "strain sqrt(eps^2 + gamma^2/3) on a proportional path). ON by "
             "default; beside resultant cells EFAIL is named, not converted. "
             "MEASURED on spotweld.k with --spotweld-node-synthesis "
             "--beam-contact-secondary (nt 4): rupture 1.12650e-3 s vs "
             "LS-DYNA 1.17969e-3..1.19792e-3 s (4.6-6.0 %% early). Its only "
             "default mover is a giant the campaign does not run (measurable "
             "default effect nil). Use --no-spotweld-efail-displacement to "
             "keep EFAIL dropped.",
    )
    parser.add_argument(
        "--implicit-tshell-solid",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="On an IMPLICIT deck (the modal path included), write an "
             "isotropic *SECTION_TSHELL whose parts are all *MAT_ELASTIC as "
             "/PROP/SOLID Isolid 14 (Inpts 222) on the same /BRICK rows "
             "instead of /PROP/TYPE20: the implicit thick-shell tangent "
             "integrates the thickness with ONE mid-plane point "
             "(s8cke3.F:354-364) and 80 + 4 coupon runs stop at cycle 0. ON "
             "by default; explicit decks keep TYPE20, other laws and "
             "TYPE21 / TYPE22 keep their card with a named warning. "
             "MEASURED: ex_02_thick_shell_elform_{2,3,5} timeout (cycle "
             "100 624) -> NORMAL in 28 cycles (nt 4 and 2); ex_15 energy "
             "error 74.1 -> -0.7 %% at 0.64x the cycles (named cost: END IE "
             "+0.03 -> +36.49 %%). Use --no-implicit-tshell-solid to keep "
             "/PROP/TYPE20.",
    )
    parser.add_argument(
        "--corotational-orthotropic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write an element-frame orthotropic /PROP/TYPE6 (Ip 20 / 21 / 23 "
             "/ 24, LS-DYNA AOPT 0 / 1 / 3 / 4) co-rotational: the MAT_126 "
             "honeycomb's pinned Isolid 1 gets Iframe 2, and an Ip 21 / 24 "
             "orthotropic brick on Isolid 17 is written as Isolid 14 like "
             "Ip 20 / 23 since round 6; on Ip 21 /MAT/LAW93's 2 / 3 "
             "constants are exchanged (Radioss b = e_z x a, "
             "smorth3.F:324-327). ON by default. MEASURED on one-hex coupons "
             "at nt 4: MAT_126 crush 0 -> 12 of 12 cases right (sigma(0.10) "
             "6.0047 -> 1.5049 against 1.5), LAW93 Ip 24 0 -> 6 of 6, Ip 21 "
             "2 -> 6 of 6; the plateau unchanged (RMS 0.164 %%). Tetrahedra "
             "are named, not changed. Use --no-corotational-orthotropic for "
             "the 65ff389 cards.",
    )
    parser.add_argument(
        "--mat-null-pc-mu",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write the *MAT_NULL PC and MU cells on the /MAT/HYD_VISC of "
             "every *MAT_NULL + *EOS_* carrier: Pmin = PC (PC 0.0 or blank "
             "-> -1e-20: LS-DYNA cuts at zero, hm_read_mat06.F:154 reads "
             "Pmin 0 as -INFINITY; PC > 0 refused) and Nu = MU / RO "
             "(kinematic, m6law.F:98) only where every part of the material "
             "is a *SECTION_SOLID ELFORM 6 on a deck without *INITIAL_VOID. "
             "The ELFORM-12 void floor keeps precedence; with "
             "--no-initial-void-floor alone a PC-0 void gets -1e-20 from "
             "this rule. ON by default. MEASURED at nt 4: sph/bird IE "
             "+69.44 -> +4.50 %% (0.832x cycles), channel_B -98.89 -> "
             "-0.09 %%, channel_A -98.88 -> -4.03 %%; underwater_A/B stay "
             "within 1 %%. Use --no-mat-null-pc-mu to keep Pmin 0 and Nu 0.",
    )
    parser.add_argument(
        "--joint-screw-gjoint",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Convert *CONSTRAINED_JOINT_SCREW between two *MAT_RIGID bodies "
             "into /GJOINT/RACK (Lagrange multipliers; FscaleV = -1/PARM) "
             "with a synthesized carriage, the bodies' constraints and drive "
             "re-written as /BCS/LAGMUL + /IMPVEL/LAGMUL, and the rigid pair "
             "split out of an all-parts self-contact. ON by default. The "
             "joint is exact where LS-DYNA's default penalty joint yields; "
             "SMP only (-np 1). MEASURED on EXP_SC_JOINT_SCREW at nt 4: nut "
             "travel 0 -> 185.70 mm against LS-DYNA's 183.59, IE -100 -> "
             "+42.76 %%, 0.9998x cycles. Use --no-joint-screw-gjoint to keep "
             "the joint skipped.",
    )
    parser.add_argument(
        "--tgmult-imptemp",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Turn a *MAT_THERMAL_* TGMULT (volumetric heat generation) into "
             "an /IMPTEMP holding the closed-form adiabatic solution "
             "T(t) = T0 + (TGMULT/(rho*Cp))*INTEGRAL(f dt) over the parts' own nodes. ON "
             "by default, and gated HARD: it fires only when the deck states "
             "NO other temperature driver. The gate names every spelling it "
             "screens, and it screens ALL THREE drop buckets - what k2rad "
             "converts, what it does not parse at all, and what it parses and "
             "declines - so the *BOUNDARY_TEMPERATURE_RSW / _TRAJECTORY / "
             "_PERIODIC_SET, *BOUNDARY_THERMAL_WELD / _BULKNODE / _BULKFLOW "
             "and *BOUNDARY_FLUX_TRAJECTORY spellings block it too, not just "
             "the *BOUNDARY_{TEMPERATURE,CONVECTION,FLUX,RADIATION} and "
             "*LOAD_HEAT_* ones. The ONE exception is the "
             "*LOAD_THERMAL_OPTION family on a *CONTROL_SOLUTION SOLN 1 or 2 "
             "deck, which LS-DYNA itself ignores there (Vol I R17 p.33-162) "
             "and k2rad drops for the same reason - and a TGMULT only ever "
             "acts on such a deck. The gate exists because /IMPTEMP is a hard "
             "Dirichlet reset "
             "applied every cycle (fixtemp.F:180-199) and would OVERWRITE a "
             "conduction solution rather than add to it. "
             "*INITIAL_TEMPERATURE is the T0 of that closed form, not a "
             "blocker. MEASURED on thermal/thermal-stress (TGMULT 10, "
             "TGRLC 0, RHO0_CP 1): the free-expansion displacement of node 2 "
             "goes from exactly 0.0 - all 500 states, all channels - to "
             "1.49531e-04 mm at t = 2.994002 - +0.21 %% against the "
             "LS-DYNA nodout's NEAREST SAMPLE (1.49216e-04 at t = 2.99) and "
             "+0.007 %% against the closed form at the same time - at 406580 "
             "cycles and 0 ERROR / 0 WARNING. "
             "Quote the DISPLACEMENT: that deck's LS reference energies are "
             "structural zeros.",
    )
    parser.add_argument(
        "--eig",
        action="store_true",
        dest="emit_eig",
        help="Modal decks (*CONTROL_IMPLICIT_EIGENVALUE): emit the classic /EIG "
             "request + one-shot eigensolve engine for COMMERCIAL Altair Radioss. "
             "By default the modal deck is converted to the stiffness-export "
             "recipe instead (/IMPL/PRINT/STIF writes the assembled K matrix; "
             "solve the modes offline with tools/modal_solve.py), because the "
             "open-source OpenRadioss engine cannot solve /EIG.",
    )

    # ── Force-control implicit stabilization (all opt-in; default output is
    #    byte-identical when none are given) ──────────────────────────────────
    fc = parser.add_argument_group(
        "force-control implicit stabilization",
        "Opt-in fixes for a *LOAD_RIGID_BODY pulling a clearance-fit pin held "
        "only by penalty contact (TYPE7). With none given the deck is unchanged.",
    )
    fc.add_argument(
        "--ground-springs",
        action="store_true",
        help="Inject soft /PROP/TYPE8 grounding springs on every force-loaded "
             "rigid body's loaded translational DOFs (bootstraps the singular "
             "t=0 tangent). Off by default.",
    )
    fc.add_argument(
        "--ground-spring-k",
        type=float,
        default=100.0,
        metavar="K",
        help="Grounding-spring stiffness in N/mm per loaded axis (default 100).",
    )
    fc.add_argument(
        "--inter-gapmin",
        action="append",
        default=[],
        metavar="ID=VAL",
        help="Override /INTER/TYPE7 Gapmin (field 3) on interface ID to VAL (mm). "
             "Repeatable. Drop a pulled clearance-fit interface below its nodal "
             "clearance so it starts with 0 initial penetrations. (.k-native: set "
             "the contact's Card-3 SST/MST so (SST+MST)/2 = the gap you want.)",
    )
    fc.add_argument(
        "--soften-stfac",
        type=float,
        default=None,
        metavar="STFAC",
        help="Set Stfac (penalty stiffness scale) on ALL /INTER/TYPE7 interfaces "
             "(e.g. 0.3) as contact-chatter insurance; overrides the per-contact "
             "Card-3 SFS mapping. Default: engine auto (0). (.k-native per contact: "
             "set Card-3 SFS, e.g. SFS=0.3.)",
    )
    fc.add_argument(
        "--tie-stfac",
        type=_tie_stfac_arg,
        default=None,
        metavar="VALUE|auto",
        help="Set STFAC (the penalty-tie stiffness scale) on every "
             "/INTER/TYPE10 tie. 'auto' asks for 100x the local element "
             "stiffness, i.e. 100*3(1-2nu) from the tie's main side (120 at "
             "nu = 0.3). Default: leave STFAC 0, which the starter turns into "
             "Radioss's own 0.2 — MEASURED on a determinate two-hex coupon "
             "that is a -67.6 %% tie (0.167x the stiffness of the element it "
             "welds); 30 reaches -0.76 %% and 120 reaches +0.05 %%, at "
             "dt x 0.115 and dt x 0.058 (dt scales as 1/sqrt(STFAC)). Only "
             "IMPLICIT ties and ties with an all-rigid secondary side use "
             "/INTER/TYPE10 at all; an explicit tie gets /INTER/TYPE2, which "
             "reproduces the same coupon exactly at no time-step cost.",
    )
    fc.add_argument(
        "--auto-gapmin",
        action="store_true",
        help="Set each surface-to-surface interface's Gapmin from the minimum "
             "node-to-node clearance between its two parts (Gapmin = "
             "--gapmin-factor × clearance), instead of hand-tuning Card-3 SST/SBST "
             "per mesh. An explicit --inter-gapmin still wins. Off by default.",
    )
    fc.add_argument(
        "--gapmin-factor",
        type=float,
        default=0.8,
        metavar="F",
        help="Fraction of the measured clearance used for --auto-gapmin / "
             "--suggest-gapmin (default 0.8). <1 keeps the gap below the clearance "
             "(0 initial penetration); lower it if an interface still pre-penetrates, "
             "raise it toward 1.0 if a contact fails to engage.",
    )
    fc.add_argument(
        "--derived-gapmin",
        action="store_true",
        help="Write an explicit Gapmin on every /INTER/TYPE7 whose MAIN surface "
             "is SOLID segments only and whose Gapmin would otherwise be 0 "
             "(Gapmin = --derived-gapmin-factor x the smallest main-surface "
             "segment side, ceiling 0.5 x that side). OFF by default. Without "
             "it the starter derives its own gap, 0.1 x that side "
             "(i7sti3.F:1055-1063 -- DXM only ever accumulates shell "
             "thickness, so a solid main takes the EM01*GAPMX fallback), while "
             "LS-DYNA's offset on a solid segment is ZERO unless SLDTHK > 0 is "
             "stated (Vol I R17 p.11-101/103). A default-ON WARNING names the "
             "derived value on every carrier whether or not this flag is set. "
             "MEASURED on twobar (10 mm bars, derived GAP MIN 1.0): the "
             "starter's gap ENDS at +1151 %% internal energy against the "
             "LS-DYNA reference 3036.17 and this flag's 0.005 x 10 = 0.05 ends "
             "at -5.60 %%, but that is the last instant: the first impact "
             "reads -91 %% and the engine energy error stays -7.1 to -8.2 %% "
             "at every gap. It is OPT-IN because two rounds of arms - round 6 "
             "alone ran 16 gap values on twobar, hemi, sphere1 and bend - "
             "found ZERO campaign verdict promotions (sphere1 -1.66 %% -> "
             "-7.77 %% at 4.1x the cycles; bend worse; "
             "4.3_General_Nonlinearity mixed; pend.imp and 06_heating_plate "
             "byte-inert; of the class's 15 interfaces on 14 deck keys, "
             "counted before round 6's shell-offset Gapmin took bend's, SEVEN "
             "have a measured arm and EIGHT are unjudgeable). The cost: below "
             "a deck-specific knee the cycle count grows as ~1/Gapmin - "
             "twobar 2.17x at 0.02 and 7.71x at 0.005, sphere1 3.45x at 0.05 "
             "and 5.48x at 0.02 - because the contact step is 1/2 (GAPV - "
             "PENE)/v (i7for3.F:762-770), and on a developing contact the "
             "cost grows with time (hemi at 0.7322: 0.92x at t 0.4158, 1.48x "
             "at t 0.8049). "
             "A press-fit "
             "*CONTACT_*_INTERFERENCE and k2rad's own injected implicit "
             "stabilization stub are excluded.",
    )
    fc.add_argument(
        "--derived-gapmin-factor",
        type=float,
        default=0.005,
        metavar="F",
        help="Fraction of the smallest main-surface segment side used by "
             "--derived-gapmin (default 0.005). Every value below is an END "
             "state, not an answer: on twobar the factors end at -5.60 %% "
             "(0.005), +14.45 %% (0.01), -15.22 %% (0.001) and -55.83 %% "
             "(1e-4, at 43x the cycles), while the first impact reads -91 %% "
             "at 0.005 and the energy error stays -7.1 to -8.2 %%; cycles "
             "grow as ~1/factor below the deck's knee (twobar 2.17x at "
             "0.002, 7.71x at 0.0005).",
    )
    fc.add_argument(
        "--suggest-gapmin",
        action="store_true",
        help="Print the suggested per-interface Gapmin (min nodal clearance between "
             "each contact's two parts) and exit WITHOUT converting. Inspect before "
             "applying with --auto-gapmin.",
    )
    fc.add_argument(
        "--rigid-secondary-swap",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="On an EXPLICIT deck, rescue a *CONTACT whose SECONDARY (SSID) "
             "side is WHOLLY RIGID instead of losing the whole interface. ON "
             "by default. /INTER/TYPE7 is an asymmetric node-to-segment "
             "contact, so the DEFORMABLE side must supply the tracked nodes: "
             "k2rad swaps the roles when the MSID side carries deformable "
             "nodes, and keeps the rigid secondary group when BOTH sides are "
             "wholly rigid. The starter does NOT refuse /RBODY members in a "
             "TYPE7 node group - measured at 0 ERROR(S) - so the old drop was "
             "a k2rad policy, not a solver constraint. MEASURED: sphere1 "
             "internal energy 0 (-100 %%) -> 77 830 (-1.66 %%) against the "
             "LS-DYNA reference 79 147.3; EXP_SC_CONTACT_INTERFERENCE -100 %% "
             "-> -42.8 %%; boundary_prescribed_motion.blow-mold from a "
             "diverging 241 934-cycle run at t = 0.0061 of 0.015 to NORMAL "
             "TERMINATION at t = 0.015 in 25 675 cycles. IMPLICIT decks keep "
             "the drop either way: every restoration arm on bumper diverges at "
             "ISTOP = -2 at nt 2 and nt 4.",
    )
    fc.add_argument(
        "--deformable-to-rigid",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Honour *DEFORMABLE_TO_RIGID (the plain spelling): the named "
             "part is rigid FROM t = 0 and is emitted as an /RBODY through the "
             "same path a *MAT_RIGID part takes, keeping its own material "
             "(Vol I R17 p.18-1). ON by default. Its elements are then "
             "DEACTIVATED, so the part no longer controls the time step: "
             "MEASURED on pend.imp, the controlling element goes SOLID at "
             "dt 1.360e-06 to TRUSS at dt 1.794e-05 - LS-DYNA's own "
             "1.79363E-05 - and the deck's energy error goes 99.9 %% to "
             "-0.0 %% (internal energy 5.162e5 to 5.901e-06 against the "
             "LS-DYNA reference 5.03545e-06) in 9 480 cycles where LS-DYNA "
             "takes 9 479. That -0.0 %% is the ENGINE's own energy balance, "
             "not a deviation from the reference: the campaign row still "
             "reads ie_dev +17.19 %% and stays a deviation, both energies "
             "being structural zeros on a gravity pendulum. The FIDELITY "
             "channel here is the KINETIC energy - 21.8702 against 21.874, "
             "-0.017 %%. The run-time-triggered options (_AUTOMATIC, "
             "_INERTIA, *RIGID_DEFORMABLE_*) are refused by name; they have 0 "
             "carriers on every corpus this converter is measured against.",
    )
    fc.add_argument(
        "--deformable-contact-recipe",
        action="store_true",
        help="Apply the validated stabilization recipe for an implicit deck with "
             "deformable-vs-deformable contact (e.g. force control through a "
             "clearance-fit deformable pin): /INTER/TYPE7 Inacti=5 on each "
             "deformable-deformable interface, plus /IMPL/DT/2 L_dtn=50 and "
             "/IMPL/QSTAT/DTSCAL=0.05. Off by default; without it the converter "
             "only warns when such contact is detected. Implicit decks only.",
    )
    parser.add_argument(
        "--blast-ground",
        default="auto",
        metavar="MODE",
        help="Ground plane for a surface-burst /LOAD/PBLAST (Exp_data=2). "
             "'auto' (default) infers the vertical axis from geometry and "
             "synthesizes a reflecting ground plane through the charge so all "
             "target segments load; 'none' emits no Ground_ID (OpenRadioss's "
             "wrong-for-non-Z-up default) and only warns; X/Y/Z/-X/-Y/-Z force "
             "the ground-normal (up) axis.",
    )
    parser.add_argument(
        "--rigid-cog-master",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Synthesize an element-free /RBODY master node at each *MAT_RIGID "
             "part's nodal centroid (the treatment CNRBs always get) instead of "
             "reusing the part's lowest-id mesh node. ON by default: clears "
             "starter WARNINGs 448/1624, keeps mesh nodes at their source "
             "coordinates (OpenRadioss otherwise relocates the mesh-node master "
             "to the centre of mass at runtime), and makes the deck "
             "AMS-compatible (a mesh-node master trips AMS ERROR 1066). Use "
             "--no-rigid-cog-master to reuse the mesh node as master instead "
             "(keeps the master-node id stable for scripts that address "
             "loads/readouts by it).",
    )
    parser.add_argument(
        "--zero-density-floor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Substitute rho = 1e-24 (in the deck's own units) for a material "
             "that states RO <= 0. ON by default: the OpenRadioss starter "
             "refuses a non-positive density outright "
             "(hm_read_mat.F90:1575-1583, ERROR 683), while LS-DYNA accepts "
             "the card and makes the SAME substitution silently — its own "
             "d3hsp reports a part mass of exactly 1.000e-24 x volume, "
             "measured on five R14 reference decks. A static or eigenvalue "
             "answer is unaffected (the /IMPL/QSTAT stabilization is "
             "proportional to the mass and simply vanishes with it); an "
             "EXPLICIT deck gets a second warning, because at that density "
             "the element time step collapses to ~1e-14 s and the run will "
             "never finish. A material converting to a law the starter exempts "
             "(LAW0/20/51/108/151/999 — *MAT_VACUUM above all) is left alone. "
             "Use --no-zero-density-floor to copy the deck's own RO through "
             "and let the starter refuse it.",
    )
    parser.add_argument(
        "--zero-t0-sentinel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write /HEAT/MAT T0 as 1e-10 (in the deck's own temperature "
             "unit) when the deck STATES an initial temperature of exactly "
             "0.0. ON by default: Radioss cannot tell a stated 0 from 'not "
             "stated' - hm_read_therm.F:236-237 turns a zero T0 into 300 K "
             "and scoor3.F:328-338 / cinmas.F:900-905 then overwrite every "
             "node still at exactly 0.0 with it, so the run starts 300 K "
             "away from where the deck says it starts. Both are EXACT zero "
             "tests, so the value is a sentinel dodge, not physics. "
             "MEASURED on ex_22_solid_elform_2: node 5 at t = 31.60 s reads "
             "198.21400 against the LS-DYNA reference's 34.83880 (+468.9 "
             "percent) with T0 = 0 and 35.15680 (+0.91 percent) with the "
             "sentinel. A deck that states no initial temperature at all "
             "keeps 0.0. Use --no-zero-t0-sentinel to write the deck's own "
             "0.0.",
    )
    parser.add_argument(
        "--node-tc-rc-bcs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Convert *NODE card 1's own TC/RC constraint cells (Vol I R17 "
             "p.35-2: NID X Y Z TC RC, codes 0 none, 1 x, 2 y, 3 z, 4 xy, "
             "5 yz, 6 zx, 7 xyz, in the GLOBAL system) into one /GRNOD/NODE + "
             "/BCS per distinct (TC, RC) pair. ON by default: LS-DYNA applies "
             "those cells unconditionally, and this decode reproduces its own "
             "d3hsp 'nodal spc summary on *NODE cards' echo (printed by 155 of "
             "the R14 reference runs) on all 162139 constrained *NODE rows "
             "(267641 non-zero TC/RC cells) of the 137 "
             "carrier decks, with zero translation-code disagreements. Without it the DOFs are FREE at 0 warnings and 0 "
             "starter errors: on the 356-deck dynaexamples R14 campaign 137 "
             "decks carry a non-zero cell and 119 of them have no "
             "*BOUNDARY_SPC at all. MEASURED against their own LS-DYNA "
             "glstat: component1 IE -99.92 %% / KE +772630 %% becomes IE "
             "+1.5 %% / KE +1.0 %%, and ex_03_solid_elform_1_4x6x4_mesh goes "
             "from a TIMESTEP-LIMIT death at t = 0.22 to NORMAL TERMINATION "
             "at t = 1.0. Screened per rule and every screen counted in the "
             "log: rigid-body member nodes DROPPED (Vol I p.35-3 Remark 1; "
             "inert anyway, rgbodv.F:150-155), DOFs a "
             "*BOUNDARY_PRESCRIBED_MOTION drives left to it (a /BCS on the "
             "same DOF measures a 99.9 %% engine energy error), DOFs a "
             "*BOUNDARY_SPC already states merged rather than restated. Use "
             "--no-node-tc-rc-bcs to keep those DOFs free.",
    )
    parser.add_argument(
        "--default-hourglass",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Give a 1-point *SECTION_SOLID that the deck leaves DEFAULTED "
             "LS-DYNA's own default hourglass control. ON by default. Vol I "
             "R17 p.12-271 *CONTROL_HOURGLASS Remark 1: 'If omitted or if "
             "IHQ = 0, the default hourglass control types are as follows: "
             "... b) For solids: type 2 for explicit; type 6 for implicit', "
             "with QH 0.1 (a stated QH/QM of 0.0 is that same default - "
             "birdball.k states IHQ 2 / QH 0.0 and its own d3hsp echoes "
             "'hourglass coefficient = 1.00000E-01'). Those go through the "
             "existing IHQ -> Isolid remap, i.e. Isolid 1 (viscous, "
             "Belytschko) explicit and Isolid 24 (HEPH) implicit, instead of "
             "the full-integration Isolid 17 - which prop_p14_solid.cfg calls "
             "'2*2*2 Integration Points, No Hourglass' and for which "
             "hm_read_prop14.F:369-372 forces the coefficient to ZERO. "
             "MEASURED against each deck's own LS-DYNA glstat: sloshing_A "
             "goes from a TIMESTEP-LIMIT death at t = 0.18 to NORMAL "
             "TERMINATION at t = 2.0 (IE -0.25 %%), sloshing_C from a timeout "
             "to NORMAL (+2.82 %%), taylor_A from IE +2.56 %% / KE +1.48 %% "
             "to +0.00 %% / -0.03 %%, rodsol from +2.88 %% / +4.04 %% to "
             "-1.72 %% / +1.41 %%, and the IMPLICIT ex_03_solid_elform_1 from "
             "-20.38 %% to -4.14 %%. Screened out: ELFORM -1/-2 (Vol I "
             "p.41-104 Remark 13 - no hourglass energy at all), ELFORM 2/3/16 "
             "and the tets (no hourglass modes), ALE sections, /MAT/LAW115 "
             "sections (own measured remap) and any deck with an "
             "*INITIAL_STRESS_SECTION (Isolid 1/2 hit zero-or-negative volume "
             "at cycle 0 under /PRELOAD). A *MAT_NULL / *MAT_ELASTIC_FLUID "
             "section keeps the VISCOUS Isolid 1 even implicitly (Vol I "
             "p.25-3 *HOURGLASS Remark 4). Use --no-default-hourglass to keep "
             "the pre-2026-09 full-integration, no-hourglass output.",
    )
    parser.add_argument(
        "--assumed-strain-isolid",
        choices=("24", "none"),
        default="none",
        help="What *SECTION_SOLID ELFORM -1 and -2 -- LS-DYNA's "
             "ASSUMED-STRAIN 8-point hexes -- land on. Default 'none' = the "
             "shipped /PROP/SOLID Isolid 17, which IS the locking ELFORM-2 "
             "element those two formulations exist to replace (Vol I R17 "
             "p.41-104 Remark 13). '24' writes HEPH (one Gauss point with "
             "physical stabilisation) instead, with LS-DYNA's own default "
             "QH 0.1 in the h cell when the deck states no hourglass card. "
             "ELFORM 2 and 3 are NOT touched. Reach: 22 deck keys on 18 "
             "emitted models state ELFORM -1/-2; the flag moves 19 keys on "
             "17 models (the ex_12 pair is already at 24 through its own "
             "*HOURGLASS IHQ 6). OPT-IN because the arms disagree, measured "
             "against each deck's own LS-DYNA reference at nt 4 (17 -> 24): "
             "ex_03_solid_elform_-1_4x6x4_mesh -21.72 %% -> -5.87 %% and "
             "ex_04_solid_elform_-1 -5.84 %% -> -2.83 %% get BETTER, while "
             "ex_14_solid_elform_-1/-2 go +313.9/+494.0 %% -> +1373/+2014 %%, "
             "mainboltaexpl -72.72 %% -> -81.40 %% at the same 51762 cycles "
             "(base-paired at nt 4), and "
             "ex_27_solid_elform_-2_rigidwall LOSES the class's only match "
             "(ke +9.75 %% -> +15.43 %%). dyna2rad maps -1 -> 24 and 2/3 -> "
             "18 (convertprops.cxx:398-402).",
    )
    parser.add_argument(
        "--implicit-rigid-secondary-swap",
        action="store_true",
        help="On an IMPLICIT deck, SWAP the two sides of a *CONTACT whose "
             "SECONDARY (SSID) side is wholly rigid instead of DROPPING the "
             "interface. OFF by default. The flag implies the derived Gapmin "
             "on the interface it creates and refuses to swap without one, so "
             "it reaches only a main surface built of SOLID segments. "
             "MEASURED on implicit/basic-examples/contact-i/bumper.k at nt 2 "
             "AND nt 4 against the LS-DYNA reference IE 1.23131e7: the "
             "shipped drop is a NORMAL-terminating ZERO MODEL (IE 0, "
             "-100 %%); the bare swap ERRORs at t 3.0e-4 (ISTOP -2, MESSAGE "
             "ID 79); swap + Gapmin 0.1499 with Inacti 0 reaches NORMAL "
             "TERMINATION in 131 cycles at t 0.05 with IE 6.934e5 "
             "(-94.4 %%), and 1.473e6 (-88.0 %%) with /IMPL/QSTAT/DTSCAL 1. "
             "So it buys a load path that is still 94 %% short, and the "
             "campaign verdict cannot move: bumper's LS-DYNA KE is exactly 0. "
             "--deformable-contact-recipe is NOT widened to reach it -- its "
             "DTSCAL 0.05, hand-set on this converted deck, drives its "
             "internal energy to -7.418e5 at the same 131 cycles -- "
             "NEGATIVE.",
    )
    parser.add_argument(
        "--mass-weighted-inivel",
        action="store_true",
        help="Give a rigid body that an *INITIAL_VELOCITY / _NODE / "
             "_GENERATION card covers only PARTLY the MOMENTUM AVERAGE Vol I "
             "R17 p.28-129 Remark 3 describes, as /INIVEL/TRA + /INIVEL/ROT "
             "on its /RBODY main node. OFF by default. Without it such a body "
             "gets the card's FULL velocity (an all-rigid card) or nothing at "
             "all (a mixed card). MEASURED on "
             "intro-by-j.-day/joint/joint-ii/translat.k at nt 4, where 2 of "
             "rigid part 1's 4 element nodes carry v = (2286, 0, 7620) and "
             "LS-DYNA's own cycle-0 K-ENERGY is 189.962: the shipped "
             "full-velocity re-point reads 387.9 (+104.20 %%), this rule "
             "reads 220.58 (+16.12 %%), and the final ke_dev goes +194.03 %% "
             "-> +47.82 %%. J = -SUM(IN) (the body's shell nodes' lumped "
             "rotary inertia, which the starter ADDS to the tensor, "
             "inirby.F:166-168/:355) is written BY DEFAULT since round 7 "
             "(--rigid-shell-rotary-inertia); this flag adds it only where "
             "the default did not (--no-rigid-shell-rotary-inertia restores "
             "the round-6 pass on every body it re-points): NEW INERTIA "
             "0.1977227E-02 = LS-DYNA's, "
             "cycle-0 KE 189.96 (LS 189.962), final KE -1.97 %% (an end value: "
             "the KE history RMS goes 17.5 %% -> 11.6 %% of the LS peak), "
             "1.156x the cycles; the IE (the joint path) is not fixed. OPT-IN because "
             "exactly ONE carrier with an LS-DYNA reference exists on this "
             "machine. A body the card FULLY covers is untouched by "
             "construction (its momentum average IS the card's velocity, with "
             "omega 0).",
    )
    parser.add_argument(
        "--law106-shell-restate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Restate a *MAT_ELASTIC_PLASTIC_THERMAL / *MAT_CWM as "
             "/MAT/LAW36 when every part on it is a SHELL and it carries a "
             "thermal expansion coefficient. ON by default, because a "
             "/MAT/LAW106 SHELL DOES NOT THERMALLY EXPAND AT ALL: "
             "cmain3.F:348 runs THERMEXPC after MULAWC at :320 and all "
             "THERMEXPC does on a /PROP/SHELL is SUBTRACT the thermal stress "
             "from the stress the law just produced, while "
             "sigeps106c.F90:297-298 rebuilds it from the TOTAL strain and "
             "never reads the old one. MEASURED on a controlled coupon "
             "(alpha 1.2e-5, dT 100 K, L 10 mm, closed form 1.2e-2 mm): "
             "LAW106 shell 0.0000000e+00 (-100 %%), the LAW36 restatement "
             "1.2000000e-02 (+0.000 %%, and identical to a *MAT_024 control "
             "run at every printed T01 digit), the LAW106 SOLID "
             "1.2000000e-02 (+0.000 %%) — solids are never restated. The cost "
             "is named per "
             "card: LAW36 has no temperature dependence, so E, nu and the "
             "yield are frozen at the reference temperature. Use "
             "--no-law106-shell-restate to keep /MAT/LAW106 and its E(T) at "
             "the price of zero thermal expansion on those parts.",
    )
    parser.add_argument(
        "--write-restart",
        action="store_true",
        help="Keep OpenRadioss's engine restart (.rst) files. By default the "
             "engine deck gets /RFILE/OFF because the restart files are only "
             "needed for /RERUN or crash recovery and are large on a big model. "
             "(The starter's <root>_0000_*.rst model-handoff file is always "
             "written and cannot be disabled.)",
    )
    parser.add_argument(
        "--ams",
        action="store_true",
        help="Advanced Mass Scaling. For a mass-scaled explicit deck "
             "(*CONTROL_TIMESTEP DT2MS<0), emit /DT/AMS + /AMS instead of "
             "/DT/NODA/CST. AMS holds the target time step with a coupled mass "
             "matrix that preserves low-frequency dynamics, instead of adding "
             "real nodal mass whose inertia can dominate a fine mesh. It solves "
             "a PCG each cycle and CAN DIVERGE ('AMS IS LIKELY DIVERGING') on "
             "stiff / high-contrast / contact-heavy models or at a large Tmin "
             "ratio — if it does, drop --ams (falls back to /DT/NODA/CST) or "
             "lower |DT2MS|. Implies --rigid-cog-master. Off by default.",
    )
    parser.add_argument(
        "--shell-formulation",
        choices=("qbat", "qeph"),
        default="qbat",
        help="Which /PROP/SHELL Ishell an LS-DYNA shell ELFORM with no exact "
             "Radioss counterpart maps to — above all ELFORM=2 "
             "(Belytschko-Tsay), the most common one. 'qbat' (default) emits "
             "Ishell=12, fully integrated, and is what every previous "
             "conversion produced. 'qeph' emits Ishell=24, reduced "
             "integration with physical stabilisation: closer to ELFORM=2's "
             "integration class, drops the starter's injected dn=1e-3 "
             "numerical damping, and erodes faithfully under /FAIL/JOHNSON "
             "Ifail_sh=2 (2 failure events to delete an element, not 8 — "
             "Ishell=12 under-erodes by up to ~1.7x). CHOOSING 'qeph' CHANGES "
             "RESULTS on every shell deck, which is why it is not the "
             "default. Under-integrated Ishell 1-4 is not offered: it would "
             "break /INISHE initial-stress transfer (npg 4 -> 1).",
    )
    parser.add_argument(
        "--he-bunreacted",
        type=float,
        default=None,
        metavar="K",
        help="Override the /MAT/LAW5 `Bunreacted` cell (the UNREACTED "
             "explosive's bulk modulus), in the deck's own pressure unit. "
             "Without it k2rad writes the *MAT_HIGH_EXPLOSIVE_BURN card's own "
             "K when it states one, and otherwise 0 - which is exactly "
             "LS-DYNA's p = F*p_eos on a BETA=0 card. A value is DERIVED only "
             "under --ale-multimat-law51, where fill_buffer_51.F:496 refuses a "
             "LAW51 phase whose cell is <= 0 (ERROR 99); the derivation is the "
             "JWL principal isentrope's slope at the unreacted density, "
             "A*R1*exp(-R1) + B*R2*exp(-R2) + omega*E0. That substitution is "
             "named in the log with its formula, its value and its "
             "consequence: mjwl.F:166 has no branch on the cell, so it adds "
             "(1-F)*K*mu to the applied pressure at EVERY burn fraction, where "
             "an LS-DYNA BETA=0 card carries nothing. Use this to state a "
             "measured unreacted bulk modulus instead.",
    )
    parser.add_argument(
        "--ale-multimat-law51",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Emit the synthesized /MAT/LAW51 for an "
             "*ALE_MULTI-MATERIAL_GROUP. OFF by default: k2rad writes the "
             "LS-DYNA per-fluid ALE layout (each fluid on its own /PART with "
             "its own single-material /MAT and Iale=1 on its /PROP/SOLID), so "
             "no /PART it emits ever references that card - it is an orphan BY "
             "CONSTRUCTION. MEASURED on underwater_C: deleting the block left "
             "all 164 T01 channels identical at all 172 samples (max "
             "|difference| exactly 0.000000e+00), at 0 ERROR / 0 WARNING / "
             "NORMAL TERMINATION. What it is NOT free of is its own starter "
             "check, fill_buffer_51.F:496, which forced a positive Bunreacted "
             "onto the material's own LIVE /MAT/LAW5 - and mjwl.F:166 makes "
             "that a real (1-F)*K*mu pre-burn stiffness an LS-DYNA BETA=0 card "
             "does not carry. Turn it on if you intend to consolidate the ALE "
             "mesh onto one /PART referencing it by hand; the Bunreacted "
             "derivation returns with it.",
    )
    parser.add_argument(
        "--dt-del",
        type=float,
        default=None,
        metavar="TMIN",
        help="Emit /DT/{SHELL,SH_3N,BRICK}/DEL with this Tmin (seconds): "
             "OpenRadioss DELETES any element whose time step reaches it. "
             "Opt-in, and off unless given — the card removes mass and "
             "stiffness the LS-DYNA original may have kept. Without it a "
             "deletion floor is emitted only when the deck asks, i.e. "
             "*CONTROL_TIMESTEP ERODE=1 with TSLIMT>0. Use it as an escape "
             "hatch for a long run where one degrading element drags the "
             "global step toward zero. Pick the value as a DELETION "
             "threshold, not a mass-scaling target: ~0.9x the initial step "
             "deletes elements that merely stretched ~10%%, ~0.4-0.5x "
             "reserves it for near-total element collapse. Coexists with "
             "/DT/NODA/CST (the deletion test uses the element's geometric "
             "step and runs before the NODADT return), but interacts with "
             "--ams, which is warned about.",
    )
    parser.add_argument(
        "--eroding-surf-ext",
        action="store_true",
        help="Build the SOLID side of a *CONTACT_ERODING_* contact from "
             "/SURF/PART/EXT (external skin only) instead of the default "
             "/SURF/PART/ALL. /ALL is the default because it is what makes "
             "eroding contact WORK: the starter puts every interior "
             "(two-solid) face in the segment list with a negative stiffness "
             "and the engine flips it active the moment one of its two solids "
             "dies — LS-DYNA's IADJ=1 / EROSOP=1 behaviour exactly. With /EXT "
             "the face a dying brick exposes has no contact segment, no "
             "stiffness and no friction, and NOTHING in the solver output says "
             "so. Use this flag only to reproduce LS-DYNA SMP's literal "
             "IADJ=0, or when the extra interior segments make contact sorting "
             "too expensive. (Quadratic solids fall back to /EXT on their own: "
             "the 2022 Reference Guide p.372 wants /EXT there so the mid-side "
             "nodes take part in the contact.)",
    )
    parser.add_argument(
        "--airbag-particle-uniform",
        action="store_true",
        help="Convert *AIRBAG_PARTICLE to a UNIFORM-PRESSURE "
             "/MONVOL/AIRBAG1 instead of the finite-volume /MONVOL/FVMBAG2 it "
             "maps to. FVMBAG2 is the faithful target and stays the default, "
             "but it CANNOT RUN on an open-source OpenRadioss build: "
             "hm_read_monvol_type11.F hard-wires KMESH=14, init_monvol.F "
             "dispatches that to HYPERMESH_TETRA, and starter/stub/"
             "fvmbags_stub.F is a stub that prints 'FVMBAGS require a mesher' "
             "and STOPs. MEASURED: the reader echoes the whole /MONVOL "
             "cleanly, then the starter dies before writing a restart file. "
             "This flag trades the finite-volume pressure field — the whole "
             "point of a CPM bag — for a bag that actually inflates. The gas "
             "species, the injector, the vents and the porous surfaces are "
             "identical either way; only the pressure field is uniform.",
    )
    return parser


def main(argv=None) -> int:
    # Windows consoles often use cp1252, which cannot encode the arrows/units
    # glyphs used in warning texts - degrade gracefully instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        try:
            # TextIO does not declare reconfigure (it is TextIOWrapper's); the
            # AttributeError arm below IS the "this stream has none" case, so
            # the probe is deliberate and the ignore is scoped to that one code.
            stream.reconfigure(errors="replace")   # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 1

    # Read-only inspection: report suggested Gapmins and exit (no conversion).
    if args.suggest_gapmin:
        from .gapmin import analyze_file
        return _print_gapmin_suggestions(str(input_path), args.gapmin_factor, analyze_file)

    # Parse --inter-gapmin ID=VAL pairs into {id: gapmin}.
    inter_gapmin = {}
    for item in args.inter_gapmin:
        if "=" not in item:
            print(f"ERROR: --inter-gapmin expects ID=VAL, got {item!r}", file=sys.stderr)
            return 1
        sid, _, sval = item.partition("=")
        try:
            inter_gapmin[int(sid.strip())] = float(sval.strip())
        except ValueError:
            print(f"ERROR: --inter-gapmin ID and VAL must be numeric: {item!r}",
                  file=sys.stderr)
            return 1

    from . import convert

    print(f"Converting: {input_path}")
    result = convert(
        input_path=str(input_path),
        output_stem=args.output_stem,
        units=tuple(args.units),
        ground_springs=args.ground_springs,
        ground_spring_k=args.ground_spring_k,
        inter_gapmin=inter_gapmin,
        soften_stfac=args.soften_stfac,
        tie_stfac=args.tie_stfac,
        tet10_to_tet4=args.tet10_to_tet4,
        auto_gapmin=args.auto_gapmin,
        gapmin_factor=args.gapmin_factor,
        derived_gapmin=args.derived_gapmin,
        derived_gapmin_factor=args.derived_gapmin_factor,
        rigid_secondary_swap=args.rigid_secondary_swap,
        deformable_to_rigid=args.deformable_to_rigid,
        fixpoint_count=args.fixpoint_count,
        qstat_dtscal=args.qstat_dtscal,
        arclength_riks=args.arclength_riks,
        zero_tolerance_ectol=args.zero_tolerance_ectol,
        implicit_constant_step=args.implicit_constant_step,
        discrete_offset=args.discrete_offset,
        spring_token_mass_compensation=args.spring_token_mass_compensation,
        shell_to_solid_rbody=args.shell_to_solid_rbody,
        generalized_weld_butt=args.generalized_weld_butt,
        initial_void_floor=args.initial_void_floor,
        weld_exponents=args.weld_exponents,
        constrained_linear=args.constrained_linear,
        constrained_global=args.constrained_global,
        spotweld_node_synthesis=args.spotweld_node_synthesis,
        beam_contact_secondary=args.beam_contact_secondary,
        shell_offset_gapmin=args.shell_offset_gapmin,
        rigid_shell_rotary_inertia=args.rigid_shell_rotary_inertia,
        spotweld_shear_yield=args.spotweld_shear_yield,
        spotweld_efail_displacement=args.spotweld_efail_displacement,
        implicit_tshell_solid=args.implicit_tshell_solid,
        corotational_orthotropic=args.corotational_orthotropic,
        mat_null_pc_mu=args.mat_null_pc_mu,
        joint_screw_gjoint=args.joint_screw_gjoint,
        tgmult_imptemp=args.tgmult_imptemp,
        deformable_contact_recipe=args.deformable_contact_recipe,
        emit_eig=args.emit_eig,
        blast_ground=args.blast_ground,
        rigid_cog_master=args.rigid_cog_master,
        zero_density_floor=args.zero_density_floor,
        law106_shell_restate=args.law106_shell_restate,
        zero_t0_sentinel=args.zero_t0_sentinel,
        node_tc_rc_bcs=args.node_tc_rc_bcs,
        default_hourglass=args.default_hourglass,
        assumed_strain_isolid=args.assumed_strain_isolid,
        implicit_rigid_secondary_swap=args.implicit_rigid_secondary_swap,
        mass_weighted_inivel=args.mass_weighted_inivel,
        write_restart=args.write_restart,
        ams=args.ams,
        shell_formulation=args.shell_formulation,
        dt_del=args.dt_del,
        he_bunreacted=args.he_bunreacted,
        ale_multimat_law51=args.ale_multimat_law51,
        eroding_surf_ext=args.eroding_surf_ext,
        airbag_particle_uniform=args.airbag_particle_uniform,
        progress=None if args.quiet else _make_progress_printer(),
    )

    print(f"  Starter -> {result.starter_path}")
    print(f"  Engine  -> {result.engine_path}")
    if result.log_path:
        print(f"  Log     -> {result.log_path}")

    if not args.quiet:
        if result.skipped_keywords:
            print(f"\n  Skipped (unsupported) keywords ({len(result.skipped_keywords)}):")
            for kw in result.skipped_keywords:
                print(f"    *{kw}")

        if result.recognized_not_emitted:
            print(f"\n  Recognized but not emitted "
                  f"({len(result.recognized_not_emitted)}) — parsed, not "
                  f"counted as skipped, but no card was written:")
            for kw, reason in result.recognized_not_emitted:
                print(f"    *{kw}: {reason}")

        if result.warnings:
            print(f"\n  Warnings ({len(result.warnings)}):")
            for w in result.warnings:
                print(f"    {w}")

    if result.warnings or result.skipped_keywords or result.recognized_not_emitted:
        print("\nConversion complete (with warnings). Review output before running.")
    else:
        print("\nConversion complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
