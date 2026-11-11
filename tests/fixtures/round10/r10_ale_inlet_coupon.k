*KEYWORD
*TITLE
resA2 ALE inlet coupon
*CONTROL_TERMINATION
    1.0E-4
*CONTROL_TIMESTEP
       0.0       0.8         0       0.0       0.0         0         0         0
*CONTROL_ALE
         0         1         1      -1.0       0.0       0.0       0.0       0.0
       0.0     1E+20       1.0       0.0       0.0         0       0.0         0
*PART
water
         1         1         1         1
*SECTION_SOLID
         1        11         0
*MAT_NULL
         1    1.0E-9       0.0       0.0       0.0       0.0       0.0       0.0
*EOS_GRUNEISEN
         1 1500000.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0
*PART
vacuum
         2         2         2
*SECTION_SOLID
         2        11         0
*MAT_VACUUM
         2   1.0E-14
*ALE_MULTI-MATERIAL_GROUP
         1         1
         2         1
*DEFINE_CURVE
         1         0       1.0       1.0       0.0       0.0
                 0.0            -20000.0
                 1.0            -20000.0
*SET_NODE_LIST
         1
        13        14        15        16
*BOUNDARY_PRESCRIBED_MOTION_SET
         1         2         0         1       1.0         0       0.0       0.0
*SET_PART_LIST
         2
         1
*INITIAL_VELOCITY_GENERATION
         1         2       0.0       0.0  -20000.0       0.0         0         0
       0.0       0.0       0.0       0.0       0.0       0.0         0         0
*ELEMENT_SOLID
       1       2       1       2       3       4       5       6       7       8
       2       1       5       6       7       8       9      10      11      12
       3       1       9      10      11      12      13      14      15      16
*NODE
       1             0.0             0.0             0.0       7       0
       2             0.0             0.0            10.0       7       0
       3            10.0             0.0            10.0       7       0
       4            10.0             0.0             0.0       7       0
       5             0.0            10.0             0.0       0       0
       6             0.0            10.0            10.0       0       0
       7            10.0            10.0            10.0       0       0
       8            10.0            10.0             0.0       0       0
       9             0.0            20.0             0.0       0       0
      10             0.0            20.0            10.0       0       0
      11            10.0            20.0            10.0       0       0
      12            10.0            20.0             0.0       0       0
      13             0.0            30.0             0.0       6       0
      14             0.0            30.0            10.0       6       0
      15            10.0            30.0            10.0       6       0
      16            10.0            30.0             0.0       6       0
*END
