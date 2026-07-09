"""Add soft grounding springs to a force-control OpenRadioss starter (.rad).

NOTE: For a FRESH conversion, prefer the integrated converter flag
``python k2rad.py model.k --ground-springs [--ground-spring-k K]`` (k2rad.writer
._make_grounding_springs), which auto-detects the *LOAD_RIGID_BODY master node
and its loaded axes. This standalone script remains useful for PATCHING an
already-generated .rad in place (e.g. a pre-existing starter you do not want to
reconvert) — it emits the same /PROP/TYPE8 grounding-spring block.

WHY
---
The hr-anlenkung 6 kN load case is force-controlled: a *LOAD_RIGID_BODY 6 kN +Y
is applied to the loading-pin rigid body, whose master node is FREE in Y and Z
(MAT_RIGID con1=1 -> only X + rotations fixed). The pin and the deformable
bracket are held to ground only through clearance-fit contact (pin<->bracket
~0.105 mm, bracket<->fixed-cyl ~0.134 mm), so at t=0 the tangent stiffness is
singular in the load direction (rigid-body modes) and implicit Newton cannot
build a reaction -> frozen residual, I-ENERGY == 0. Displacement control hides
this by imposing the pin Y/Z motion; force control does not.

This script adds the Altair-documented fix (UserGuide p.483 "add artificial
springs with small stiffness to connect the free parts"): a weak /PROP/TYPE8
(SPR_GENE) grounding spring on the pin master node in global Y and Z. It removes
the singular mode while staying soft enough that contact carries the load once
it engages (spring reaction ~= k * pin_disp, a few % of 6 kN at k~100 N/mm).

It grounds ONLY the pin; the deformable bracket's early-time rigid motion is
carried by the QSTAT inertia stabilization (/IMPL/QSTAT/DTSCAL 0.1), exactly as
in the working displacement-control deck. If the bracket itself stalls, ground a
couple of bracket nodes the same way.

CARD DETAILS (verified against OpenRadioss source + hm_cfg):
  * /PROP/TYPE8 linear spring: set only the stiffness K; the reader forces
    A=1,B=0,E=0 when no function is given and converts zero failure
    displacements to +/-1e30 (no rupture). MASS must be > 0 (use a tiny value).
  * Spring /PART with mat_ID=0 is fine: the starter auto-creates a fictitious
    spring material (hm_read_part.F).
  * Springs are assembled into the implicit tangent (engine assem_r3.F); a
    constant-K spring needs no /IMPL/SPRING keyword.

USAGE
-----
  python add_grounding_springs.py in_0000.rad out_0000.rad
  python add_grounding_springs.py in_0000.rad out_0000.rad --node 51386955 --ky 100 --kz 100
"""

import argparse
import os


def find_node_coords(path, node_id):
    """Return the (x, y, z) coordinate strings of node_id from a /NODE block."""
    target = str(node_id)
    in_node = False
    with open(path, "r", errors="replace") as f:
        for ln in f:
            s = ln.rstrip("\n")
            if s.startswith("/NODE"):
                in_node = True
                continue
            if in_node and s.startswith("/"):
                in_node = s.startswith("/NODE")
                continue
            if in_node:
                toks = s.split()
                if toks and toks[0] == target:
                    return toks[1], toks[2], toks[3]
    raise SystemExit(f"node {node_id} not found in a /NODE block of {path}")


def build_spring_block(node_id, xyz, ky, kz, *, ground_node, grnod, bcs,
                       prop, part, elem, mass=1.0e-4, inertia=1.0e-6):
    f20 = lambda x: f"{x:>20g}"
    i10 = lambda x: f"{x:>10d}"
    s20 = lambda x: f"{x:>20}"

    def dof(k):  # 3 data lines per SPR_GENE DOF; linear -> only K, rest 0
        return [
            "#                 K                   C                   A                   B                   D",
            f20(k) + f20(0) + f20(0) + f20(0) + f20(0),
            "#  fct_ID1         H   fct_ID2   fct_ID3   fct_ID4                      DeltaMin            DeltaMax",
            i10(0) * 5 + "          " + f20(0) + f20(0),
            "#                 F                   E              Ascale              Hscale",
            f20(0) + f20(0) + f20(0) + f20(0),
        ]

    b = [
        "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|",
        f"#-- SOFT GROUNDING SPRINGS (force-control stabilization): pin master node {node_id}, global Y & Z.",
        "/NODE",
        i10(ground_node) + s20(xyz[0]) + s20(xyz[1]) + s20(xyz[2]),
        f"/GRNOD/NODE/{grnod}", "spring_ground_node", i10(ground_node),
        f"/BCS/{bcs}", "fix_spring_ground",
        "#  Tra rot   skew_ID  grnod_ID", "   111 111         0" + i10(grnod),
        f"/PROP/TYPE8/{prop}", "soft_ground_spring_pin_YZ",
        "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
        f20(mass) + f20(inertia) + i10(0) * 6,
    ]
    b += dof(0.0) + dof(ky) + dof(kz) + dof(0.0) + dof(0.0) + dof(0.0)  # X Y Z RX RY RZ
    b += [
        # Closing ISRATE card — without it the SPR_GENE reader overruns into
        # the following /PART (starter WARNING 100217 "card is missing"); same
        # fix the integrated writer got for its /PROP/TYPE8 block.
        "#  Fsmooth                Fcut",
        i10(0) + f20(0.0),
    ]
    b += [
        f"/PART/{part}", "soft_ground_spring_part", i10(prop) + i10(0) + i10(0),
        f"/SPRING/{part}", "# sprg_ID  node_ID1  node_ID2",
        i10(elem) + i10(node_id) + i10(ground_node),
    ]
    return "\n".join(b) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Inject pin grounding springs into a starter .rad")
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--node", type=int, default=51386955, help="pin RBODY master node id")
    ap.add_argument("--ky", type=float, default=100.0, help="global-Y grounding stiffness [N/mm]")
    ap.add_argument("--kz", type=float, default=100.0, help="global-Z grounding stiffness [N/mm]")
    ap.add_argument("--ground-node", type=int, default=88000001)
    ap.add_argument("--grnod", type=int, default=88000010)
    ap.add_argument("--bcs", type=int, default=88000011)
    ap.add_argument("--prop", type=int, default=8001)
    ap.add_argument("--part", type=int, default=8002)
    ap.add_argument("--elem", type=int, default=88000005)
    a = ap.parse_args()

    xyz = find_node_coords(a.infile, a.node)
    block = build_spring_block(a.node, xyz, a.ky, a.kz, ground_node=a.ground_node,
                               grnod=a.grnod, bcs=a.bcs, prop=a.prop, part=a.part, elem=a.elem)

    injected = False
    with open(a.infile, "r", errors="replace") as fi, open(a.outfile, "w", newline="\n") as fo:
        for ln in fi:
            if (not injected) and ln.strip() == "/END":
                fo.write(block)
                fo.write("/END\n")
                injected = True
                continue
            fo.write(ln if ln.endswith("\n") else ln + "\n")

    if not injected:
        raise SystemExit("no /END found; nothing injected")
    print(f"pin node {a.node} @ ({xyz[0]}, {xyz[1]}, {xyz[2]})  ky={a.ky} kz={a.kz}")
    print(f"wrote {a.outfile}  ({os.path.getsize(a.outfile)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
