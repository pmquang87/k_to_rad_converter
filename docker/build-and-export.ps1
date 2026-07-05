<#
  build-and-export.ps1 - build the OpenRadioss+MUMPS+Vortex+k2rad image and
  export it to a .tar your colleague can load. Requires the base image
  openradioss-mumps-vortex:20260520 to exist locally (build that first if
  needed). NOTE: this layer rebuilds the OpenRadioss engine with the modal
  patches, so the first build takes a while (tens of minutes).
#>
param(
  [string]$Context = $PSScriptRoot,
  [string]$Tag     = "openradioss-k2rad:20260703",
  [string]$OutTar  = (Join-Path $PSScriptRoot "openradioss-k2rad-20260703.tar")
)

Write-Host "Building $Tag (layered on openradioss-mumps-vortex:20260520)..." -ForegroundColor Cyan
docker build -t $Tag $Context
if ($LASTEXITCODE -ne 0) { Write-Error "docker build failed (exit $LASTEXITCODE)"; exit $LASTEXITCODE }

Write-Host "Exporting image -> $OutTar" -ForegroundColor Cyan
docker save $Tag -o $OutTar
if ($LASTEXITCODE -ne 0) { Write-Error "docker save failed (exit $LASTEXITCODE)"; exit $LASTEXITCODE }

$sizeGB = [math]::Round((Get-Item $OutTar).Length / 1GB, 2)
Write-Host ""
Write-Host "Done. Image tar: $OutTar ($sizeGB GB)" -ForegroundColor Green
Write-Host "Give that .tar (plus or.ps1) to your colleague. On their machine:"
Write-Host "    docker load -i `"$([System.IO.Path]::GetFileName($OutTar))`""
