#!/usr/bin/env bash
#
# build-and-export.sh - build the OpenRadioss+MUMPS+Vortex+k2rad image and
# export it to a .tar your colleague can load. Bash equivalent of
# build-and-export.ps1 (Linux / macOS).
#
# Requires the base image openradioss-mumps-vortex:20260520 to exist locally
# (build that first if needed). NOTE: this layer rebuilds the OpenRadioss
# engine with the modal patches, so the first build takes a while (tens of
# minutes).
set -euo pipefail

# --- Single source of truth for the image tag -------------------------------
# Default to the moving :latest tag; overridable via the K2RAD_IMAGE env var.
# The image is tagged both :latest and the dated tag so exported tars stay
# self-identifying, while scripts can keep pointing at :latest.
K2RAD_IMAGE_DATE="${K2RAD_IMAGE_DATE:-20260703}"
IMAGE="${K2RAD_IMAGE:-openradioss-k2rad:latest}"
DATED_IMAGE="${K2RAD_IMAGE_DATED:-openradioss-k2rad:${K2RAD_IMAGE_DATE}}"

# Build context defaults to this script's directory; output tar sits beside it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="${1:-${SCRIPT_DIR}}"
OUT_TAR="${2:-${SCRIPT_DIR}/openradioss-k2rad-${K2RAD_IMAGE_DATE}.tar}"

echo "Building ${IMAGE} (+ ${DATED_IMAGE}) (layered on openradioss-mumps-vortex:20260520)..."
docker build -t "${IMAGE}" -t "${DATED_IMAGE}" "${CONTEXT}"

echo "Exporting image -> ${OUT_TAR}"
docker save "${DATED_IMAGE}" -o "${OUT_TAR}"

# Report the tar size in GB (portable across GNU/BSD stat).
if bytes="$(stat -c '%s' "${OUT_TAR}" 2>/dev/null)" || bytes="$(stat -f '%z' "${OUT_TAR}" 2>/dev/null)"; then
  size_gb="$(awk "BEGIN { printf \"%.2f\", ${bytes}/1073741824 }")"
  echo ""
  echo "Done. Image tar: ${OUT_TAR} (${size_gb} GB)"
else
  echo ""
  echo "Done. Image tar: ${OUT_TAR}"
fi
echo "Give that .tar (plus or.sh) to your colleague. On their machine:"
echo "    docker load -i \"$(basename "${OUT_TAR}")\""
