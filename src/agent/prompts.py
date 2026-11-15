"""Token-efficient prompts for local Ollama (qwen2.5-coder:7b).
Each prompt is scoped to a single endpoint or small group to avoid context overflow.
"""

UNIT_TEST_SYSTEM = """You are a senior QA engineer. Generate pytest test functions using httpx.
Rules:
- Use synchronous test functions (def test_..., NOT async def). The `client` fixture is a synchronous httpx.Client.
- Call client synchronously: response = client.get(...) or client.post(...), NEVER use await.
- Test ONLY what the OpenAPI spec says
- Include: happy path (200/201), validation error (422), auth error (401)
- Never read source code - only test via HTTP
- Output ONLY valid Python code, no explanations"""

UNIT_TEST_TEMPLATE = """Generate pytest unit tests for this endpoint:
PATH: {method} {path}
OPERATION_ID: {operation_id}
REQUIRES_AUTH: {requires_auth}
SUCCESS_CODE: {success_status_code}
REQUEST_BODY_SCHEMA: {request_body}
PATH_PARAMS: {path_params}
RESPONSE_SCHEMA: {response_schema}
EXAMPLE_PAYLOAD: {example_payload}

Use `client` fixture (httpx.Client) and `auth_headers` fixture (Bearer token).
Generate 3-5 test functions. Output ONLY Python code."""

E2E_SYSTEM = """You are a senior QA engineer. Generate Playwright pytest tests for multi-step API journeys.
Rules:
- Use APIRequestContext from playwright
- Test stateful flows: Register→Login→Create→Mutate→Delete
- Use pytest fixtures for shared state
- Output ONLY valid Python code"""

E2E_TEMPLATE = """Generate a Playwright pytest E2E test for this user journey:
JOURNEY_NAME: {journey_name}
STEPS: {steps}
API_BASE_URL: {base_url}
ENDPOINT_SCHEMAS: {endpoint_schemas}

Also include a Chromium smoke test that:
1. Opens {base_url}/docs
2. Checks the page title contains "Swagger"
3. Checks at least one endpoint is visible

Output ONLY Python code."""

HEAL_SYSTEM = """You are a senior QA engineer doing self-healing test repair.
BLACK-BOX RULE: You cannot read the target app source code. Only use the OpenAPI spec and test output.
Classify failures STRICTLY:
- TEST_BUG: bad syntax, wrong payload, missing auth headers, wrong status code assertion vs spec, broken test ordering
- API_BUG: test is correct per spec but server returns 500 or violates response schema

Output ONLY valid Python code with the fixed/decorated test function."""

HEAL_TEMPLATE = """Analyze this test failure and fix it:
ORIGINAL_TEST:
{original_test}

FAILURE_TRACEBACK:
{traceback}

OPENAPI_SPEC_FOR_ENDPOINT:
{endpoint_spec}

CLASSIFICATION_RULES:
- If the test assertion was wrong (e.g. asserted 204 but spec says 200): TEST_BUG → fix the assertion
- If the payload was malformed: TEST_BUG → fix payload using EXAMPLE_PAYLOAD above
- If server returned 500 and test correctly expected 200/201/204: API_BUG → add @pytest.mark.xfail(reason="API_BUG: ...", strict=True)
- If test has syntax error or async def issues: TEST_BUG → rewrite as synchronous test

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
