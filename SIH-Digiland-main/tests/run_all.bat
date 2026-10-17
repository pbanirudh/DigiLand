@echo off
REM ============================================================================
REM DigiLand Comprehensive Test Suite Runner
REM Executes Backend Unit Tests, Integration Tests, Data Validation, Security,
REM Performance Benchmarking, and Automated UI Screenshots.
REM ============================================================================

echo ============================================================================
echo   DIGILAND AUTOMATED TEST SUITE RUNNER
echo   SIH 2026 Problem Statement 26018 - Land Record Digitization
echo ============================================================================
echo.

echo [1/5] Running Backend Unit Tests (pytest tests/test_unit_backend.py)...
python -m pytest tests/test_unit_backend.py -v
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Unit tests encountered errors!
    exit /b %ERRORLEVEL%
)
echo.

echo [2/5] Running API Integration Tests (pytest tests/test_api_integration.py)...
python -m pytest tests/test_api_integration.py -v
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] API integration tests encountered errors!
    exit /b %ERRORLEVEL%
)
echo.

echo [3/5] Running Data-Driven Validation (pytest tests/test_data_validation.py)...
python -m pytest tests/test_data_validation.py -v -s
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Data validation tests encountered errors!
    exit /b %ERRORLEVEL%
)
echo.

echo [4/5] Running Non-Functional, Security and Performance Benchmarks...
python -m pytest tests/test_non_functional.py -v -s
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Non-functional tests encountered errors!
    exit /b %ERRORLEVEL%
)
echo.

echo [5/5] Capturing UI Viewports and Endpoint Screenshots...
python tests/capture_screenshots.py
echo.

echo ============================================================================
echo   ALL DIGILAND TEST SUITES COMPLETED SUCCESSFULLY!
echo   Report available at: tests\TEST_REPORT.md
echo   Screenshots available at: tests\screenshots\
echo ============================================================================
