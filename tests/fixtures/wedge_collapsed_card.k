*KEYWORD
$ The SAME 10 x 10 x 10 mm block as tests/fixtures/wedge_short_card.k, meshed as
$ two pentahedra written the way LS-DYNA spells one: an eight-column
$ *ELEMENT_SOLID card with the bottom and top triangles each collapsed by
$ repeating their last node (N1 N2 N3 N3 N5 N6 N7 N7). Every one of the 7417
$ pentahedra on the R14 corpus uses this spelling. The two decks must produce
$ the same two wedges and the same starter TOTAL MASS.
*TITLE
Wedge coupon - collapsed eight-node cards
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
       1       1       1       2       3       3       5       6       7       7
       2       1       1       3       4       4       5       7       8       8
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
