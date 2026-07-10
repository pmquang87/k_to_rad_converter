"""
k2rad.topology  –  neutral element-connectivity facts shared across the package.

These are pure mesh-topology constants/helpers with no dependency on the writer
or the parser, so both the writer and the optional ``gapmin`` proximity path can
import them without dragging in the whole output stage. (Previously
``gapmin.py`` reached into ``writer._TET10_MIDEDGE`` directly.)
"""

# Mid-edge node -> (corner A, corner B) of its edge, in the LS-DYNA/Abaqus/
# Nastran 10-node tet convention (*ELEMENT_SOLID ten-node figure, R16 Vol I):
# node5=mid(1,2), node6=mid(2,3), node7=mid(1,3),
# node8=mid(1,4), node9=mid(2,4), node10=mid(3,4).
# Indices are 0-based positions into the 10-node connectivity list.
# (An earlier map had nodes 8/9/10 cyclically rotated — mid(2,4)/mid(3,4)/
# mid(1,4) — which made _snap_tet10_midsides relocate the apex mid-edge nodes
# of every STANDARD tet10 mesh onto the wrong edges.)
TET10_MIDEDGE = [(4, 0, 1), (5, 1, 2), (6, 0, 2), (7, 0, 3), (8, 1, 3), (9, 2, 3)]

# Convenience: {frozenset(cornerA, cornerB): mid-node index} for edge lookups.
TET10_EDGEMID = {frozenset((a, b)): m for (m, a, b) in TET10_MIDEDGE}
