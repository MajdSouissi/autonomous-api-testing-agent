"""Token-efficient prompts for local Ollama (qwen2.5-coder:7b).
Each prompt is scoped to a single endpoint or small group to avoid context overflow.
"""

UNIT_TEST_SYSTEM = """You are a senior QA engineer. Generate pytest test functions using httpx.
Rules:
- Use synchronous test functions (def test_..., NOT async def). The `client` fixture is a synchronous httpx.Client.
- Call client synchronously: response = client.get(...) or client.post(...), NEVER use await.
- Test ONLY what the OpenAPI spec says.
- Include: happy path (200/201), validation error (422), auth error (401/403).

CRITICAL CONTENT-TYPE PRECISION:
- Check CONTENT_TYPE for the endpoint:
  * ONLY use `data=payload` when an endpoint's OpenAPI requestBody schema specifically declares `application/x-www-form-urlencoded` (e.g. POST /auth/token).
  * Standard endpoints like `POST /auth/register` and `POST /items/` use `application/json` and MUST use `json=payload` (`client.post(url, json=payload)`). NEVER use `data=payload` for JSON endpoints.
  * For registration tests (POST /auth/register), use unique usernames: `username = f"user_{uuid.uuid4().hex[:8]}"` and send with `json={"username": username, "password": "password123"}`.

FIXTURE & AUTH RULES:
- Use `client` fixture (httpx.Client) and `auth_headers` fixture for endpoints that require authentication (`headers=auth_headers`).
- NEVER mutate the `auth_headers` fixture in-place (do NOT do `auth_headers["Authorization"] = ...`).
  If testing unauthorized/invalid token (401), either omit headers (`client.get(url)`), or pass a separate dict: `client.get(url, headers={"Authorization": "Bearer invalid_token"})`.
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

CONTENT-TYPE & CALL RULES:
- ONLY use `data=payload` when CONTENT_TYPE is specifically `application/x-www-form-urlencoded` (e.g. POST /auth/token).
- When CONTENT_TYPE is `application/json` (such as POST /auth/register, POST /items/, PUT /items/{{path_param}}): you MUST call `client.post(path, json=payload)` or `client.put(path, json=payload)`. NEVER use data= for JSON endpoints!
- For POST /auth/register: MUST use `json=payload` with a unique username (`f"user_{{uuid.uuid4().hex[:8]}}"`).
- For POST /auth/token: MUST use `data=payload` (`application/x-www-form-urlencoded`).
- Use `client` fixture (httpx.Client) and `auth_headers` fixture (Bearer token).
- Generate 3-5 test functions. Output ONLY Python code."""

E2E_SYSTEM = """You are a senior QA engineer. Generate Playwright pytest tests for multi-step API journeys.
Rules:
- BROWSER LAUNCH: ALWAYS use `browser = p.chromium.launch(headless=True)` then `context = browser.new_context(base_url=base_url)`. NEVER call `p.chromium.new_context(...)` — that method does not exist.
- API CALLS: Use `context.request.post(...)`, `context.request.get(...)`, etc. (APIRequestContext via `.request`).
- PAYLOAD ENCODING — CRITICAL: Playwright's APIRequestContext DOES NOT support `json=`. You MUST use `data=payload_dict` for ALL request bodies (register, create item, update item). Playwright automatically serializes dict → JSON. NEVER use `json=payload`.
- DYNAMIC USERS: ALWAYS generate unique usernames with `uuid.uuid4().hex[:6]` to prevent collision on repeated runs. Never hardcode usernames.
- For /auth/token (OAuth2 form-urlencoded): ALWAYS use `form={{"username": username, "password": password}}` — NOT `data=`. This sets Content-Type: application/x-www-form-urlencoded as required by FastAPI OAuth2PasswordRequestForm.
- SMOKE TEST: Always call `page.goto("/docs")` and assert `re.search(r"Swagger UI", page.title()) is not None`.
- Always `import re`, `import uuid` at the top of the file.
- Output ONLY valid Python code"""

E2E_TEMPLATE = """Generate a Playwright pytest E2E test for this user journey:
JOURNEY_NAME: {journey_name}
STEPS: {steps}
API_BASE_URL: {base_url}
ENDPOINT_SCHEMAS: {endpoint_schemas}

IMPORTANT E2E RULES:
- BROWSER FIXTURE: `browser = p.chromium.launch(headless=True)` → `context = browser.new_context(base_url=base_url)`. Yield context. On teardown: `context.close(); browser.close()`.
- PAYLOAD ENCODING — CRITICAL: Use `data=payload_dict` for ALL request bodies (NEVER `json=payload`). Examples:
  * Register:  `context.request.post("/auth/register", data={{"username": username, "password": password}})`
  * Token:     `context.request.post("/auth/token", form={{"username": username, "password": password}})` ← MUST use form= for OAuth2 (sets Content-Type: application/x-www-form-urlencoded)
  * Create:    `context.request.post("/items/", headers=headers, data={{"title": "...", "description": "...", "price": "10.0"}})`
- DYNAMIC USERS: generate username as `f"user_{{uuid.uuid4().hex[:6]}}"` — NEVER hardcode.
- SMOKE TEST: use `page = context.new_page(); page.goto("/docs")` and assert `re.search(r"Swagger UI", page.title()) is not None`. Wrap in try/finally to call `page.close()`.
- Always add `import re` and `import uuid` at the top of the file.

Output ONLY Python code."""

HEAL_SYSTEM = """You are a senior QA engineer doing self-healing test repair.
BLACK-BOX RULE: You cannot read the target app source code. Only use the OpenAPI spec and test output.

CLASSIFICATION RULES:
- Rule 1 (Server Crashes): If status code is 500/5xx and test expected 200/201/204, classify as API_BUG!
- Rule 2 (Silent Data Corruption / Contract Breach): If the test sends a valid payload, receives a 200/201 response, but an assertion comparing returned data to sent data fails (e.g. `assert 0.0 == 0.1` or `response.json()["price"] == payload["price"]`), classify as API_BUG! Reason: "Server accepted payload but returned mutated/corrupted data".
- When an API_BUG is classified, you must NOT rewrite the test to match the bad server behavior; decorate it with:
  @pytest.mark.xfail(reason="API Bug: <explanation>", strict=True)
- Rule 3 (Content-Type Precision):
  * Only use `data=payload` when an endpoint's requestBody specifically declares `application/x-www-form-urlencoded` (e.g. /auth/token).
  * Standard endpoints like `POST /auth/register` and `POST /items/` use `application/json` and MUST use `json=payload`. If a test for `/auth/register` failed with 422 because it sent `data=payload`, fix it to `json=payload`.
  * STRICT FORBIDDEN: NEVER weaken happy-path *_success tests! Never change an assertion expecting 200 or 201 on a *_success test to accept 422 or assert 'error' in response.json(). If a *_success test receives 422, fix the payload structure or use json= instead of data=.
  * Classify test syntax errors, missing auth, wrong assertion values vs spec, or using wrong payload format as TEST_BUG.

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
- Rule 3 (Content-Type Precision):
  * Endpoints with application/json (e.g. /auth/register, /items/) MUST use json=payload. If data=payload was sent, change to json=payload!
  * Endpoints with application/x-www-form-urlencoded (e.g. /auth/token) MUST use data=payload.
- Rule 4 (DO NOT WEAKEN): NEVER weaken happy-path *_success tests (e.g. never change 200/201 assertion to 422 or 'error' in response.json()). Fix payload or json=/data= parameter instead!
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
- `registered_user` fixture (session-scoped): creates a unique user via POST /auth/register using json={{"username": f"testuser_{{uuid.uuid4().hex[:8]}}", "password": "testpassword123"}}, asserts response.status_code == 201
- `auth_token` fixture (session-scoped, depends on registered_user): retrieves a valid JWT via POST /auth/token using data={{"username": registered_user["username"], "password": registered_user["password"]}}, headers={{"Content-Type": "application/x-www-form-urlencoded"}}, asserts response.status_code == 200, returns response.json()["access_token"]
- `auth_headers` fixture (function-scoped, depends on auth_token): returns a fresh dictionary {{"Authorization": f"Bearer {{auth_token}}"}}. NEVER hardcode invalid_token; dynamically create user and token.
- `playwright_base_url` fixture for Playwright tests
Output ONLY valid Python code."""
