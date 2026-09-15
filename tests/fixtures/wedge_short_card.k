*KEYWORD
$ A 10 x 10 x 10 mm block meshed as TWO pentahedra, each written on a SHORT
$ six-node *ELEMENT_SOLID card (EID PID N1..N6). Not an LS-DYNA spelling --
$ Vol I R17 p.19-124 gives the card eight node columns -- but a shape k2rad can
$ be handed, and the one the /BRICK emitter used to pad with its last node into
$ a hexahedron the reader then integrated at the wrong volume. The twin
$ tests/fixtures/wedge_collapsed_card.k is the same block on the 8-field
$ collapsed spelling; both must reach the starter as the same two wedges.
*TITLE
Wedge coupon - short six-node cards
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             0.0             0.0            10.0
       6            10.0             0.0            10.0
       7            10.0            10.0            10.0
       8             0.0            10.0            10.0
*ELEMENT_SOLID
       1       1       1       2       3       5       6       7
       2       1       1       3       4       5       7       8
*PART
wedge block
         1         1         1
*SECTION_SOLID
         1         1
*MAT_ELASTIC
         1  7.85e-9  210000.0       0.3
*CONTROL_TERMINATION
     1.0e-3
*END
