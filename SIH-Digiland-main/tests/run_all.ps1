# ============================================================================
# DigiLand Comprehensive Test Suite Runner (PowerShell)
# SIH 2026 Problem Statement 26018 - Land Record Digitization
# ============================================================================

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "  DIGILAND AUTOMATED TEST SUITE RUNNER" -ForegroundColor Cyan
Write-Host "  SIH 2026 Problem Statement 26018 - Land Record Digitization" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Stop"

try {
    Write-Host "[1/5] Running Backend Unit Tests (pytest tests/test_unit_backend.py)..." -ForegroundColor Yellow
    python -m pytest tests/test_unit_backend.py -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed!" }

    Write-Host "`n[2/5] Running API Integration Tests (pytest tests/test_api_integration.py)..." -ForegroundColor Yellow
    python -m pytest tests/test_api_integration.py -v
    if ($LASTEXITCODE -ne 0) { throw "API integration tests failed!" }

    Write-Host "`n[3/5] Running Data-Driven Validation (pytest tests/test_data_validation.py)..." -ForegroundColor Yellow
    python -m pytest tests/test_data_validation.py -v -s
    if ($LASTEXITCODE -ne 0) { throw "Data validation tests failed!" }

    Write-Host "`n[4/5] Running Non-Functional, Security & Performance Benchmarks..." -ForegroundColor Yellow
    python -m pytest tests/test_non_functional.py -v -s
    if ($LASTEXITCODE -ne 0) { throw "Non-functional tests failed!" }

    Write-Host "`n[5/5] Capturing UI Viewports and Endpoint Screenshots..." -ForegroundColor Yellow
    python tests/capture_screenshots.py

    Write-Host "`n============================================================================" -ForegroundColor Green
    Write-Host "  ALL DIGILAND TEST SUITES COMPLETED SUCCESSFULLY!" -ForegroundColor Green
    Write-Host "  Report: tests\TEST_REPORT.md" -ForegroundColor Green
    Write-Host "  Screenshots: tests\screenshots\" -ForegroundColor Green
    Write-Host "============================================================================" -ForegroundColor Green
} catch {
    Write-Host "`n[ERROR] Test run failed: $_" -ForegroundColor Red
    exit 1
}
