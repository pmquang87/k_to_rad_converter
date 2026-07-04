#!/usr/bin/env python3
"""
k2rad.py  –  CLI entry point for the LS-DYNA .k → OpenRadioss .rad converter.

Examples
--------
    python k2rad.py model.k
    python k2rad.py model.k output/model
    python k2rad.py model.k --units Mg mm s
"""

import argparse
import sys
from pathlib import Path


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
    try:
        from k2rad.gapmin import fast_proximity_available
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from k2rad.gapmin import fast_proximity_available

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
        print(f"  Or pin explicitly:  " + " ".join(
            f"--inter-gapmin {i}={suggestions[i].suggested_gapmin:g}" for i in sorted(suggestions)))
    if skipped:
        print("\n  No suggestion (set manually if needed):")
        for iid in sorted(skipped):
            print(f"    INTER {iid}: {skipped[iid]}")
    return 0


def main() -> int:
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
        default=100,
        metavar="N",
        help="Number of evenly spaced /IMPL/DT/FIXPOINT output milestones the "
             "implicit time-step controller is forced to land on (k/N x the run "
             "end, for k = 1..N; default 100 = a point every 1 percent). Clamped "
             "to the engine's 1..100 range; 0 disables the card. Implicit decks "
             "only; ignored for explicit.",
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
        "--suggest-gapmin",
        action="store_true",
        help="Print the suggested per-interface Gapmin (min nodal clearance between "
             "each contact's two parts) and exit WITHOUT converting. Inspect before "
             "applying with --auto-gapmin.",
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
        action="store_true",
        help="Synthesize an element-free /RBODY master node at each *MAT_RIGID "
             "part's nodal centroid (the treatment CNRBs always get) instead of "
             "reusing the part's lowest-id mesh node. Clears starter WARNINGs "
             "448/1624 and keeps mesh nodes at their source coordinates "
             "(OpenRadioss otherwise relocates the mesh-node master to the "
             "centre of mass at runtime). Renumbers every rigid master, so "
             "loads/readouts address the new synthesized node.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 1

    # Read-only inspection: report suggested Gapmins and exit (no conversion).
    if args.suggest_gapmin:
        try:
            from k2rad.gapmin import analyze_file
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent))
            from k2rad.gapmin import analyze_file
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

    # Import here so the CLI can be called without installing the package
    try:
        from k2rad import convert
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from k2rad import convert

    print(f"Converting: {input_path}")
    result = convert(
        input_path=str(input_path),
        output_stem=args.output_stem,
        units=tuple(args.units),
        ground_springs=args.ground_springs,
        ground_spring_k=args.ground_spring_k,
        inter_gapmin=inter_gapmin,
        soften_stfac=args.soften_stfac,
        tet10_to_tet4=args.tet10_to_tet4,
        auto_gapmin=args.auto_gapmin,
        gapmin_factor=args.gapmin_factor,
        fixpoint_count=args.fixpoint_count,
        deformable_contact_recipe=args.deformable_contact_recipe,
        emit_eig=args.emit_eig,
        blast_ground=args.blast_ground,
        rigid_cog_master=args.rigid_cog_master,
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

        if result.warnings:
            print(f"\n  Warnings ({len(result.warnings)}):")
            for w in result.warnings:
                print(f"    {w}")

    if result.warnings or result.skipped_keywords:
        print("\nConversion complete (with warnings). Review output before running.")
    else:
        print("\nConversion complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
