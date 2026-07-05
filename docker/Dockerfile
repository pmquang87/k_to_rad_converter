# OpenRadioss + MUMPS + Vortex + k2rad (LS-DYNA .k -> OpenRadioss modal chain)
# -----------------------------------------------------------------------------
# Layered on the verified openradioss-mumps-vortex image; adds the k2rad
# converter, the offline modal eigensolver (scipy) and a modal-patched engine
# so an LS-DYNA *CONTROL_IMPLICIT_EIGENVALUE deck runs end-to-end:
#   convert -> starter -> engine np=1 (exact stiffness export) -> eigensolve
#   -> d3plot/VTK mode shapes -> random-vibration PSD/RMS/fatigue post.
#
# Build:  docker build -t openradioss-k2rad:20260703 .
# -----------------------------------------------------------------------------
ARG BASE_IMAGE=openradioss-mumps-vortex:20260520
FROM ${BASE_IMAGE}

# scipy for the offline eigensolver (numpy is already present via lasso-python).
RUN python3 -m pip install --no-cache-dir scipy

# k2rad converter + modal tools. master must carry the --drill LS-DYNA-parity
# eigensolver (PR #36); the two checks fail the build if it does not.
RUN git clone --depth 1 https://github.com/pmquang87/k_to_rad_converter.git /opt/k2rad && \
    python3 -c "import sys; sys.path.insert(0,'/opt/k2rad'); import k2rad; print('k2rad import OK')" && \
    python3 /opt/k2rad/tools/modal_solve.py --help | grep -q drill && \
    echo "modal_solve --drill OK"

# Modal-patched engine: the two 1-line imp_mumps.F fixes documented in
# /opt/k2rad/README.md, "Stock-engine caveats (and the 1-line patches)":
#   (a) FORMAT label 1003: E10.2 -> E24.16 -- exact /IMPL/PRINT/STIF stiffness
#       export (the stock 2-significant-digit print costs ~0.5-1% on every
#       eigenfrequency);
#   (b) IF (NSPMD == 1) RETURN right after the per-domain file is closed --
#       the stock engine otherwise enters an O(NZ^2) multi-domain duplicate
#       merge and hangs for hours after "--STIFFNESS MATRIX IS PRINTED--"
#       on np=1 runs (the per-domain file is already complete).
RUN cd /opt/OpenRadioss/engine/source/implicit && \
    cp imp_mumps.F imp_mumps.F.orig_k2rad && \
    sed -i 's/^1003  FORMAT(I10,I10,E10\.2)/1003  FORMAT(I10,I10,E24.16)/' imp_mumps.F && \
    sed -i 's/^      CLOSE(UNIT=OFFST+ISPMD) *$/      CLOSE(UNIT=OFFST+ISPMD)\n      IF (NSPMD == 1) RETURN/' imp_mumps.F && \
    grep -q 'FORMAT(I10,I10,E24.16)' imp_mumps.F && \
    grep -q 'IF (NSPMD == 1) RETURN' imp_mumps.F && \
    echo "imp_mumps.F patched OK"

# Rebuild ONLY the engine (starter, MUMPS/ScaLAPACK/LAPACK libs are untouched;
# they are still in the image from the base build). CMake's POST_BUILD step
# installs the new engine_linux64_gf_ompi over the stock one in
# /opt/OpenRadioss/exec. The marker file asserts the install really happened;
# the binary grep asserts the patched FORMAT string was compiled in.
RUN touch /tmp/.k2rad_rebuild_marker && \
    cd /opt/OpenRadioss/engine && \
    ./build_script.sh -arch=linux64_gf -mpi=ompi -nt="$(nproc)" -release \
      -mumps_root=/opt/OpenRadioss/engine/extlib/MUMPS_5.5.1 \
      -scalapack_root=/opt/OpenRadioss/engine/extlib/scalapack-2.2.0/build/lib \
      -lapack_root=/opt/OpenRadioss/engine/extlib/lapack-3.10.1 && \
    test /opt/OpenRadioss/exec/engine_linux64_gf_ompi -nt /tmp/.k2rad_rebuild_marker && \
    grep -qa 'E24.16' /opt/OpenRadioss/exec/engine_linux64_gf_ompi && \
    echo "patched engine installed OK" && \
    rm -rf /opt/OpenRadioss/engine/cbuild_* /tmp/.k2rad_rebuild_marker

# Updated launcher (adds the `modal` and `convert` commands).
COPY orun /usr/local/bin/orun
RUN chmod +x /usr/local/bin/orun

WORKDIR /data
ENTRYPOINT ["orun"]
CMD ["help"]
