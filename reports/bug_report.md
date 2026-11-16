# API Bug Report

Generated: 2026-11-16T14:41:15.433671

## Summary
- Total API bugs caught: **2**
- These tests are marked `@pytest.mark.xfail(strict=True)` and will FAIL if the bug is fixed without updating the decorator.

## Detected Bugs

### Bug #1: E2E User Journey
- **Test:** `test_full_user_journey`
- **Reason:** Server silently mutated/corrupted data
- **Traceback excerpt:**
```
N/A
```

### Bug #2: E2E User Journey
- **Test:** `test_swagger_smoke_test`
- **Reason:** Server returned 500 Internal Server Error (unhandled server crash)
- **Traceback excerpt:**
```
generated_tests\test_e2e_playwright.py:80: in test_swagger_smoke_test
    expect(page).to_have_title("Swagger UI")
E   AssertionError: Page title expected to be 'Swagger UI'
E   Actual value: Benchmark Target API - Swagger UI 
E   Call log:
E     - Expect "to_have_title" with timeout 5000ms
E       13 × locator resolved to <html>…</html>
E          - unexpected value "Benchmark Target API - Swagger UI"
E   
E   Aria snapshot:
E   - img
E   - heading "Benchmark Target API 1.0.0 OAS 3.1" [level=1]
```
