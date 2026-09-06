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
        tet10_to_tet4=args.tet10_to_tet4,
        auto_gapmin=args.auto_gapmin,
        gapmin_factor=args.gapmin_factor,
        fixpoint_count=args.fixpoint_count,
        deformable_contact_recipe=args.deformable_contact_recipe,
        emit_eig=args.emit_eig,
        blast_ground=args.blast_ground,
        rigid_cog_master=args.rigid_cog_master,
        zero_density_floor=args.zero_density_floor,
        law106_shell_restate=args.law106_shell_restate,
        zero_t0_sentinel=args.zero_t0_sentinel,
        node_tc_rc_bcs=args.node_tc_rc_bcs,
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
