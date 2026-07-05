<#
  or.ps1 - run OpenRadioss / k2rad jobs through the Docker container.

  Modal workflow (LS-DYNA .k deck with *CONTROL_IMPLICIT_EIGENVALUE), run from
  inside the folder holding the deck. Examples:
    .\or.ps1 -KFile mymodel.k -Modal              # full chain: convert -> solve -> mode shapes (+ random post)
    .\or.ps1 -KFile mymodel.k -Modal -NModes 20   # solve 20 modes instead of the deck's NEIG
    .\or.ps1 -KFile mymodel.k -ConvertOnly        # just write mymodel_0000/_0001.rad

  Ordinary OpenRadioss runs (same as the vortex container). Examples:
    .\or.ps1 -Stem mymodel -Np 4 -Nt 1            # solve only
    .\or.ps1 -Stem mymodel -Np 4 -Nt 1 -D3plot    # solve, then anim -> d3plot
    .\or.ps1 -Stem mymodel -ConvertOnly           # convert existing anim files only
#>
param(
  [string]$KFile,                               # LS-DYNA deck (enables the k2rad commands)
  [switch]$Modal,                               # full modal chain on -KFile
  [int]$NModes = 0,                             # modes to solve (0 = the deck's NEIG)
  [string]$Stem,                                # deck stem, without _0000.rad (ordinary runs)
  [int]$Np = 4,                                 # MPI domains (SPMD)
  [int]$Nt = 1,                                 # OpenMP threads per domain
  [switch]$D3plot,                              # also convert anim -> d3plot after solving
  [switch]$ConvertOnly,                         # with -KFile: .k -> .rad only; with -Stem: anim -> d3plot only
  [string]$RunDir = (Get-Location).Path,        # folder with the model / results
  [string]$Image = "openradioss-k2rad:20260703"
)

$RunDir = (Resolve-Path -LiteralPath $RunDir).Path

if ($KFile) {
  if ($Modal) {
    Write-Host "=== k2rad modal chain : $KFile ===" -ForegroundColor Cyan
    Write-Host "    dir = $RunDir"
    $cmdArgs = @("modal", $KFile)
    if ($NModes -gt 0) { $cmdArgs += "$NModes" }
    docker run --rm --shm-size=2g -v "${RunDir}:/data" -w /data $Image @cmdArgs
    exit $LASTEXITCODE
  }
  if ($ConvertOnly) {
    Write-Host "=== k2rad convert : $KFile ===" -ForegroundColor Cyan
    Write-Host "    dir = $RunDir"
    docker run --rm -v "${RunDir}:/data" -w /data $Image convert $KFile
    exit $LASTEXITCODE
  }
  Write-Error "-KFile needs -Modal (full chain) or -ConvertOnly (.k -> .rad only)."
  exit 2
}

if (-not $Stem) {
  Write-Error "Give either -KFile <model.k> -Modal, or -Stem <stem> (ordinary run). See the header of this script."
  exit 2
}

Write-Host "=== OpenRadioss (MUMPS + Vortex) : $Stem  np=$Np nt=$Nt ===" -ForegroundColor Cyan
Write-Host "    dir = $RunDir"

if (-not $ConvertOnly) {
  docker run --rm --shm-size=2g -v "${RunDir}:/data" -w /data $Image run $Stem $Np $Nt
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($D3plot -or $ConvertOnly) {
  Write-Host "=== Converting animations -> $Stem.d3plot ===" -ForegroundColor Cyan
  docker run --rm -v "${RunDir}:/data" -w /data $Image d3plot $Stem
}
exit $LASTEXITCODE
