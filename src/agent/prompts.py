"""Token-efficient prompts for local Ollama (qwen2.5-coder:7b).
Each prompt is scoped to a single endpoint or small group to avoid context overflow.
"""

UNIT_TEST_SYSTEM = """You are a senior QA engineer. Generate pytest test functions using httpx.
Rules:
- Use synchronous test functions (def test_..., NOT async def). The `client` fixture is a synchronous httpx.Client.
- Call client synchronously: response = client.get(...) or client.post(...), NEVER use await.
- Test ONLY what the OpenAPI spec says.
- Include: happy path (200/201), validation error (422), auth error (401/403).
- Content-Type handling:
  * When an endpoint specifies application/x-www-form-urlencoded (like POST /auth/token), you MUST send form data using `client.post(url, data=payload)`. NEVER send `json=payload` for form endpoints.
  * For /auth/token specifically: register a unique user first via POST /auth/register, then call POST /auth/token with `data={"username": username, "password": password}`. Assert response.status_code == 200 and "access_token" in response.json().
  * When an endpoint specifies application/json, call client using `client.post(url, json=payload)` or `client.put(url, json=payload)`.
- Never read source code - only test via HTTP.
- Output ONLY valid Python code, no explanations."""

UNIT_TEST_TEMPLATE = """Generate pytest unit tests for this endpoint:
PATH: {method} {path}
OPERATION_ID: {operation_id}
REQUIRES_AUTH: {requires_auth}
SUCCESS_CODE: {success_status_code}
CONTENT_TYPE: {content_type}
REQUEST_BODY_SCHEMA: {request_body}
PATH_PARAMS: {path_params}
RESPONSE_SCHEMA: {response_schema}
EXAMPLE_PAYLOAD: {example_payload}

CRITICAL RULES:
- When CONTENT_TYPE is application/x-www-form-urlencoded, you MUST send form data using `client.post(url, data=payload)`. NEVER send `json=payload` for form endpoints.
- When CONTENT_TYPE is application/json, use `client.post(url, json=payload)`.
- Use `client` fixture (httpx.Client) and `auth_headers` fixture (Bearer token).
- Generate 3-5 test functions. Output ONLY Python code."""

E2E_SYSTEM = """You are a senior QA engineer. Generate Playwright pytest tests for multi-step API journeys.
Rules:
- Use APIRequestContext from playwright (e.g. `playwright.request.new_context(base_url=base_url)`)
- Test stateful flows: Register→Login→Create→Mutate→Delete
- For login/token requests (OAuth2 form-data): send form data using `form={"username": ..., "password": ...}`
- Output ONLY valid Python code"""

E2E_TEMPLATE = """Generate a Playwright pytest E2E test for this user journey:
JOURNEY_NAME: {journey_name}
STEPS: {steps}
API_BASE_URL: {base_url}
ENDPOINT_SCHEMAS: {endpoint_schemas}

IMPORTANT E2E RULES:
- In Playwright, to send OAuth2 form data to /auth/token, pass `form={{"username": username, "password": password}}`.
- For POST /items/, the payload must match the schema: `{{"title": "Item Title", "description": "Item description", "price": 10.0}}`.
- Also include a Chromium smoke test that:
  1. Opens {base_url}/docs
  2. Verifies the page title contains "Swagger"
  3. Verifies at least one API endpoint element is visible (e.g. `.opblock`)

Output ONLY Python code."""

HEAL_SYSTEM = """You are a senior QA engineer doing self-healing test repair.
BLACK-BOX RULE: You cannot read the target app source code. Only use the OpenAPI spec and test output.

CLASSIFICATION RULES:
- Rule 1 (Server Crashes): If status code is 500/5xx and test expected 200/201/204, classify as API_BUG!
- Rule 2 (Silent Data Corruption / Contract Breach): If the test sends a valid payload, receives a 200/201 response, but an assertion comparing returned data to sent data fails (e.g. `assert 0.0 == 0.1` or `response.json()["price"] == payload["price"]`), classify as API_BUG! Reason: "Server accepted payload but returned mutated/corrupted data".
- When an API_BUG is classified, you must NOT rewrite the test to match the bad server behavior; decorate it with:
  @pytest.mark.xfail(reason="API Bug: <explanation>", strict=True)
- Rule 3 (Content-Type & Test Bugs):
  * When an endpoint specifies application/x-www-form-urlencoded, you MUST send form data using `data=payload`. NEVER send `json=payload` for form endpoints.
  * STRICT FORBIDDEN: NEVER weaken happy-path *_success tests! Never change an assertion expecting 200 or 201 on a *_success test to accept 422 or assert 'error' in response.json(). If a *_success test receives 422, fix the payload structure or use data= instead of json=.
  * Classify test syntax errors, missing auth, wrong assertion values vs spec, or using json= instead of data= as TEST_BUG.

Output ONLY valid Python code with the fixed/decorated test function."""

HEAL_TEMPLATE = """Analyze this test failure and fix it:
ORIGINAL_TEST:
{original_test}

FAILURE_TRACEBACK:
{traceback}

OPENAPI_SPEC_FOR_ENDPOINT:
{endpoint_spec}

CLASSIFICATION_RULES:
- Rule 1 (Server Crashes): If status code is 500/5xx when spec expects 200/201/204: API_BUG → decorate with @pytest.mark.xfail(reason="API Bug: ...", strict=True)
- Rule 2 (Silent Data Corruption): If test sent valid payload, received 200/201, but assertion comparing returned data to sent data failed (e.g. assert 0.0 == 0.1): API_BUG → decorate with @pytest.mark.xfail(reason="API Bug: server silently mutated/corrupted data", strict=True). DO NOT modify the assertion!
- Rule 3 (Form data / Content-Type): If endpoint is application/x-www-form-urlencoded (e.g. /auth/token) and test sent json=payload: TEST_BUG → change to client.post(url, data=payload)
- Rule 4 (DO NOT WEAKEN): NEVER weaken happy-path *_success tests (e.g. never change 200/201 assertion to 422 or 'error' in response.json()). Fix payload or data= parameter instead!
- Rule 5 (Spec assertion mismatch): If test asserted wrong status code vs spec (e.g. 204 vs 200): TEST_BUG → fix assertion.

Return a JSON object with:
{{
  "classification": "TEST_BUG" or "API_BUG",
  "reason": "1 sentence explanation",
  "fixed_code": "def test_name(client):\\n    # full synchronous repaired python test function\\n"
}}
Output ONLY the JSON object, or JSON followed by ```python ... ```."""

CONFTEST_TEMPLATE = """Generate a pytest conftest.py for testing a FastAPI app at {base_url}.
Include:
- `base_url` fixture (session-scoped) returning "{base_url}"  
- `client` fixture (session-scoped) returning httpx.Client(base_url=base_url)
- `registered_user` fixture: calls POST /auth/register with {{username:"testuser_{{uuid}}", password:"testpass123"}}
- `auth_token` fixture (depends on registered_user): calls POST /auth/token (form data), returns token string
- `auth_headers` fixture: returns {{"Authorization": f"Bearer {{auth_token}}"}}
- `playwright_base_url` fixture for Playwright tests
Output ONLY valid Python code."""
