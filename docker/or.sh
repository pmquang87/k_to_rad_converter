#!/usr/bin/env bash
#
# or.sh - run OpenRadioss / k2rad jobs through the Docker container.
# Bash equivalent of or.ps1 (Linux / macOS).
#
# Modal workflow (LS-DYNA .k deck with *CONTROL_IMPLICIT_EIGENVALUE), run from
# inside the folder holding the deck. Examples:
#   ./or.sh --kfile mymodel.k --modal              # full chain: convert -> solve -> mode shapes (+ random post)
#   ./or.sh --kfile mymodel.k --modal --nmodes 20  # solve 20 modes instead of the deck's NEIG
#   ./or.sh --kfile mymodel.k --convert-only       # just write mymodel_0000/_0001.rad
#
# Ordinary OpenRadioss runs (same as the vortex container). Examples:
#   ./or.sh --stem mymodel --np 4 --nt 1           # solve only
#   ./or.sh --stem mymodel --np 4 --nt 1 --d3plot  # solve, then anim -> d3plot
#   ./or.sh --stem mymodel --convert-only          # convert existing anim files only
#
# PowerShell-style flags (-KFile, -Modal, ...) are accepted too, so muscle
# memory from or.ps1 keeps working.
set -euo pipefail

# --- Single source of truth for the image tag -------------------------------
# Default to the moving :latest tag; overridable via the K2RAD_IMAGE env var
# (e.g. K2RAD_IMAGE=openradioss-k2rad:20260703 ./or.sh ...). The dated tag is
# kept as a documented fallback so an older exported image can be selected.
K2RAD_IMAGE_DATE="${K2RAD_IMAGE_DATE:-20260703}"
IMAGE="${K2RAD_IMAGE:-openradioss-k2rad:latest}"

# --- Defaults (mirrors the param() block of or.ps1) -------------------------
kfile=""
modal=0
nmodes=0
stem=""
np=4
nt=1
d3plot=0
convert_only=0
rundir="${PWD}"

die() { echo "or.sh: $*" >&2; exit 2; }

# --- Argument parsing (accepts --flag and -Flag styles) ---------------------
while [ $# -gt 0 ]; do
  case "$1" in
    -KFile|--kfile)        kfile="${2:?-KFile needs a value}"; shift 2 ;;
    -Modal|--modal)        modal=1; shift ;;
    -NModes|--nmodes)      nmodes="${2:?-NModes needs a value}"; shift 2 ;;
    -Stem|--stem)          stem="${2:?-Stem needs a value}"; shift 2 ;;
    -Np|--np)              np="${2:?-Np needs a value}"; shift 2 ;;
    -Nt|--nt)              nt="${2:?-Nt needs a value}"; shift 2 ;;
    -D3plot|--d3plot)      d3plot=1; shift ;;
    -ConvertOnly|--convert-only) convert_only=1; shift ;;
    -RunDir|--rundir)      rundir="${2:?-RunDir needs a value}"; shift 2 ;;
    -Image|--image)        IMAGE="${2:?-Image needs a value}"; shift 2 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) die "unknown argument: $1 (see the header of this script)" ;;
  esac
done

# Resolve the run directory to an absolute path (Resolve-Path -LiteralPath).
if [ ! -d "${rundir}" ]; then
  die "run directory does not exist: ${rundir}"
fi
rundir="$(cd "${rundir}" && pwd)"

if [ -n "${kfile}" ]; then
  if [ "${modal}" -eq 1 ]; then
    echo "=== k2rad modal chain : ${kfile} ==="
    echo "    dir = ${rundir}"
    cmd_args=(modal "${kfile}")
    if [ "${nmodes}" -gt 0 ]; then cmd_args+=("${nmodes}"); fi
    docker run --rm --shm-size=2g -v "${rundir}:/data" -w /data "${IMAGE}" "${cmd_args[@]}"
    exit $?
  fi
  if [ "${convert_only}" -eq 1 ]; then
    echo "=== k2rad convert : ${kfile} ==="
    echo "    dir = ${rundir}"
    docker run --rm -v "${rundir}:/data" -w /data "${IMAGE}" convert "${kfile}"
    exit $?
  fi
  die "-KFile needs -Modal (full chain) or -ConvertOnly (.k -> .rad only)."
fi

if [ -z "${stem}" ]; then
  die "Give either --kfile <model.k> --modal, or --stem <stem> (ordinary run). See the header of this script."
fi

echo "=== OpenRadioss (MUMPS + Vortex) : ${stem}  np=${np} nt=${nt} ==="
echo "    dir = ${rundir}"

if [ "${convert_only}" -eq 0 ]; then
  docker run --rm --shm-size=2g -v "${rundir}:/data" -w /data "${IMAGE}" run "${stem}" "${np}" "${nt}"
fi

if [ "${d3plot}" -eq 1 ] || [ "${convert_only}" -eq 1 ]; then
  echo "=== Converting animations -> ${stem}.d3plot ==="
  docker run --rm -v "${rundir}:/data" -w /data "${IMAGE}" d3plot "${stem}"
fi
