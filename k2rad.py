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
    args = parser.parse_args()

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

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
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
    )

    print(f"  Starter -> {result.starter_path}")
    print(f"  Engine  -> {result.engine_path}")

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
