*KEYWORD
*TITLE
Tied node-to-surface weld
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             2.0             0.0             1.0
       6             2.0            10.0             1.0
       7             2.0             0.0            11.0
       8             2.0            10.0            11.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       8       7
*PART
face plate
         1         1         1
*PART
core stripe
         2         2         1
*SECTION_SHELL
         1         2       1.0         3
       2.0
*SECTION_SHELL
         2         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*SET_NODE_LIST_TITLE
weld_bottom_nodes
       111
         5         6
*SET_SEGMENT_TITLE
plate_core_face
       103
         1         2         3         4
*CONTACT_TIED_NODES_TO_SURFACE
       111       103         4         0
       0.0       0.0       0.0       0.0       0.0         0       0.01.0000E+28
       1.0       1.0       0.0       0.0
*CONTROL_TERMINATION
       1.0
*END
