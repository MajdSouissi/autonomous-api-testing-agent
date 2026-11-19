# API Bug Report

Generated: 2026-11-19T10:29:20.208789

## Summary
- Total API bugs caught: **2**
- These tests are marked `@pytest.mark.xfail(strict=True)` and will FAIL if the bug is fixed without updating the decorator.

## Detected Bugs

### Bug #1: POST /items/
- **Test:** `test_create_item_success`
- **Reason:** Server accepted payload but returned mutated/corrupted data (price field reset to 0.0)
- **Traceback excerpt:**
```
generated_tests\test_unit_endpoints.py:133: in test_create_item_success
    assert response.json()["price"] == payload["price"]
E   assert 0.0 == 10.99
```

### Bug #2: GET /items/{item_id}
- **Test:** `test_get_item_not_found`
- **Reason:** Server returned 500 Internal Server Error (unhandled server crash)
- **Traceback excerpt:**
```
generated_tests\test_unit_endpoints.py:216: in test_get_item_not_found
    assert response.status_code == 404
E   assert 500 == 404
E    +  where 500 = <Response [500 Internal Server Error]>.status_code
```
