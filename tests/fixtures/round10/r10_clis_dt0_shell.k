*KEYWORD
*TITLE
R14 round 10 A10 dt0 estimator fixture - the bird_B shape (shell sets it)
*CONTROL_TERMINATION
    1.0E-6
*CONTROL_TIMESTEP
       0.0       0.7         0       0.0       0.0         0         0         0
*PART
plate quad (QBAT, LAW1)
         1         1         1
*SECTION_SHELL
         1         2       1.0         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1    1.0E-9    1000.0       0.0
*PART
bird brick (ELFORM 12, LAW6)
         2         2         2         2
*SECTION_SOLID
         2        12
*MAT_NULL
         2  7.81E-10       0.0       0.0       0.0       0.0       0.0       0.0
*EOS_LINEAR_POLYNOMIAL
         2       0.0       1.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*ELEMENT_SOLID
       2       2      11      12      13      14      15      16      17      18
*NODE
       1             0.0             0.0             0.0       0       0
       2           0.661             0.0             0.0       0       0
       3           0.661           0.367             0.0       0       0
       4             0.0           0.367             0.0       0       0
      11             5.0             0.0             0.0       0       0
      12             5.5             0.0             0.0       0       0
      13             5.5             0.5             0.0       0       0
      14             5.0             0.5             0.0       0       0
      15             5.0             0.0             0.5       0       0
      16             5.5             0.0             0.5       0       0
      17             5.5             0.5             0.5       0       0
      18             5.0             0.5             0.5       0       0
*END
