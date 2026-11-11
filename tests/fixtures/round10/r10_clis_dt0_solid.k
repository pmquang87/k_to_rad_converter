*KEYWORD
*TITLE
R14 round 10 A10 dt0 estimator fixture - the quadrature shape (ALE water sets it, the rigid cube excluded)
*CONTROL_TERMINATION
    1.0E-6
*CONTROL_TIMESTEP
       0.0       0.7         0       0.0       0.0         0         0         0
*PART
ALE water (ELFORM 12, LAW6)
         1         1         1         1
*SECTION_SOLID
         1        12
*MAT_NULL
         1    1.0E-9       0.0       0.0       0.0       0.0       0.0       0.0
*EOS_GRUNEISEN
         1  100000.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0
*PART
rigid cube
         2         2         2
*SECTION_SOLID
         2         1
*MAT_RIGID
         2    1.0E-6    2.0E+5       0.3
       0.0         0         0
       0.0       0.0       0.0       0.0       0.0       0.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
       2       1       2       9      10       3       6      11      12       7
       3       2      21      22      23      24      25      26      27      28
*NODE
       1             0.0             0.0             0.0       0       0
       2            10.0             0.0             0.0       0       0
       3            10.0            10.0             0.0       0       0
       4             0.0            10.0             0.0       0       0
       5             0.0             0.0            10.0       0       0
       6            10.0             0.0            10.0       0       0
       7            10.0            10.0            10.0       0       0
       8             0.0            10.0            10.0       0       0
       9            20.0             0.0             0.0       0       0
      10            20.0            10.0             0.0       0       0
      11            20.0             0.0            10.0       0       0
      12            20.0            10.0            10.0       0       0
      21            50.0             0.0             0.0       0       0
      22            60.0             0.0             0.0       0       0
      23            60.0            10.0             0.0       0       0
      24            50.0            10.0             0.0       0       0
      25            50.0             0.0            10.0       0       0
      26            60.0             0.0            10.0       0       0
      27            60.0            10.0            10.0       0       0
      28            50.0            10.0            10.0       0       0
*END
