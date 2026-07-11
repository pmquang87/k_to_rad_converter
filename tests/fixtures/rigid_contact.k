*KEYWORD
*TITLE
Rigid body with surface-to-surface contact
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             0.0             0.0             1.0
       6             1.0             0.0             1.0
       7             1.0             1.0             1.0
       8             0.0             1.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
deformable part
         1         1         1
*PART
rigid pin
         2         1         2
*SECTION_SHELL
         1         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*MAT_RIGID
         2   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                              pin_pair
         1         2         3         3         0         0         0         0
       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20
       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0
*LOAD_RIGID_BODY
         2         3         1   -1200.0
*CONTROL_TERMINATION
       1.0
*END
