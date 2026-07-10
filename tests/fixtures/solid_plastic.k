*KEYWORD
*TITLE
Solid plasticity deck
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
*ELEMENT_SOLID
       1       1       1       2       3       4       4       4       4       4
*PART
solid
         1         1         1
*SECTION_SOLID
         1        10
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   2.7e-9   72000.0       0.3     200.0
*DATABASE_EXTENT_BINARY
         0         0         0        11         1         1         1         1
*CONTROL_TERMINATION
       1.0
*END
