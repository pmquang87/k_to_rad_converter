*KEYWORD
*TITLE
R14 round 10 A10 dt0 estimator fixture - the stagnation shape (the fixed plate sets it)
*CONTROL_TERMINATION
    1.0E-6
*CONTROL_TIMESTEP
       0.0       0.8         0       0.0       0.0         0         0         0
*PART
fixed plate (QBAT, LAW1)
         1         1         1
*SECTION_SHELL
         1         2       1.0         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1    8.0E-9  100000.0       0.0
*PART
water (ELFORM 12, LAW6)
         2         2         2         2
*SECTION_SOLID
         2        12
*MAT_NULL
         2    1.0E-9       0.0       0.0       0.0       0.0       0.0       0.0
*EOS_GRUNEISEN
         2 1500000.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*ELEMENT_SOLID
       2       2      11      12      13      14      15      16      17      18
*NODE
       1             0.0             0.0             0.0       7       7
       2           15.03             0.0             0.0       7       7
       3           15.03            10.0             0.0       7       7
       4             0.0            10.0             0.0       7       7
      11            30.0             0.0             0.0       0       0
      12            40.0             0.0             0.0       0       0
      13            40.0            10.0             0.0       0       0
      14            30.0            10.0             0.0       0       0
      15            30.0             0.0            10.0       0       0
      16            40.0             0.0            10.0       0       0
      17            40.0            10.0            10.0       0       0
      18            30.0            10.0            10.0       0       0
*END
