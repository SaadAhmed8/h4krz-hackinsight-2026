<#
.SYNOPSIS
    Runs the full Air Quality Data Warehouse pipeline on Windows.
.DESCRIPTION
    Native PowerShell fallback equivalent to 'make data'.
    Executes:
      1. Discover stations (if config/stations.yaml missing)
      2. Ingestion (OpenAQ v3 hourly + Open-Meteo ERA5 / forecast weather)
      3. Raw integrity validation against manifest.csv
      4. Cleaning, reindexing and validation (quality_log.csv)
      5. Processed mart generation (hourly_all.parquet & daily.parquet)
      6. Manifest regeneration (manifest.csv with SHA-256)
      7. Status reporting (status/run_status.json)
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Running Data Warehouse Pipeline (HackInsight 2026 - H4krz)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Execute Python pipeline module
python -m src.pipeline

if ($LASTEXITCODE -eq 0) {
    Write-Host "Pipeline execution succeeded!" -ForegroundColor Green
} else {
    Write-Host "Pipeline execution completed with exit code $LASTEXITCODE" -ForegroundColor Yellow
}
