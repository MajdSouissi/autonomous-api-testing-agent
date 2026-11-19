"""LangGraph node implementations for the autonomous API testing agent."""

import os
import json
import re
import ast
import textwrap
from pathlib import Path
from typing import Dict, Any, List, Optional

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.state import AgentState, TestResult
from src.agent.prompts import (
    UNIT_TEST_SYSTEM, UNIT_TEST_TEMPLATE,
    E2E_SYSTEM, E2E_TEMPLATE,
    HEAL_SYSTEM, HEAL_TEMPLATE,
)
from src.parser.openapi_parser import parse_spec, generate_example_payload

# --- LLM setup ---
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
GENERATED_TESTS_DIR = Path("generated_tests")
REPORTS_DIR = Path("reports")

def get_llm() -> ChatOllama:
    model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0.0,
        num_ctx=8192,
        client_kwargs={"timeout": 45.0},
        sync_client_kwargs={"timeout": 45.0},
    )

def _truncate_traceback(tb: str, max_lines: int = 20) -> str:
    """Slice a pytest traceback to only the last `max_lines` lines (the actual error & assertion)."""
    if not tb:
        return ""
    lines = tb.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)[-1500:]
    return ("... (truncated) ...\n" + "\n".join(lines[-max_lines:]))[-1500:]

def _extract_code_block(text: str) -> str:
    """Extract Python code from LLM response (strips ```python ... ``` fences)."""
    # 1. Look for explicit python code block
    py_match = re.search(r"```(?:python|py)\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if py_match:
        return py_match.group(1).strip()
    # 2. Look for any code block that does not tag json
    for match in re.finditer(r"```([a-zA-Z]*)\s*\n(.*?)```", text, re.DOTALL):
        tag = match.group(1).lower().strip()
        if tag not in ("json",):
            block = match.group(2).strip()
            if not (block.startswith("{") and block.endswith("}")):
                return block
    return text.strip()

def _extract_json_and_code(text: str) -> tuple[dict, str]:
    """Extract JSON classification and Python code from healer response."""
    classification = {}

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate_json = text[first_brace : last_brace + 1]
        try:
            parsed = json.loads(candidate_json)
            if isinstance(parsed, dict) and "classification" in parsed:
                classification = parsed
        except Exception:
            try:
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(text[first_brace:])
                if isinstance(parsed, dict) and "classification" in parsed:
                    classification = parsed
            except Exception:
                pass

    fixed_code = ""
    # If the JSON object contains fixed_code as a function string
    json_fixed_code = classification.get("fixed_code", "")
    if isinstance(json_fixed_code, str) and ("def " in json_fixed_code or "@pytest" in json_fixed_code):
        fixed_code = json_fixed_code.strip()

    # Otherwise extract from python markdown block (skipping json blocks)
    if not fixed_code:
        code_blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        for block in code_blocks:
            clean_block = block.strip()
            if clean_block.startswith("{") and clean_block.endswith("}"):
                continue
            if "def " in clean_block or "@pytest" in clean_block:
                fixed_code = clean_block
                break

    # If still not found, search raw text for function definition
    if not fixed_code:
        func_match = re.search(r"(?:@pytest[^\n]+\n)*\s*(?:async\s+)?def\s+test_[^\n]+(?:\n(?:[ \t]+.*|[ \t]*#.*|[ \t]*))*", text)
        if func_match:
            fixed_code = func_match.group(0).strip()

    # Strip any accidental leftover markdown fences
    fixed_code = re.sub(r"^```(?:python|py)?\s*\n?", "", fixed_code, flags=re.IGNORECASE)
    fixed_code = re.sub(r"\n?```\s*$", "", fixed_code)
    fixed_code = fixed_code.strip()

    if "classification" not in classification:
        if "API_BUG" in text.upper():
            classification["classification"] = "API_BUG"
        else:
            classification["classification"] = "TEST_BUG"

    return classification, fixed_code

def _add_xfail_decorator(content: str, test_name: str, reason: str) -> str:
    """Add an @pytest.mark.xfail decorator matching the function's indentation."""
    pattern = rf"(?m)^([ \t]*)(?:async\s+)?def\s+{re.escape(test_name)}\b"
    match = re.search(pattern, content)
    if not match:
        return content

    start_idx = match.start()
    # Check if xfail is already decorating this function
    prefix = content[:start_idx]
    last_block = prefix[max(0, start_idx - 300):]
    if "@pytest.mark.xfail" in last_block and not re.search(r"\bdef\s+", last_block):
        return content

    indent = match.group(1)
    escaped_reason = reason.replace('"', '\\"').replace("\n", " ").strip()
    decorator = (
        f'{indent}@pytest.mark.xfail(\n'
        f'{indent}    reason="API_BUG: {escaped_reason}",\n'
        f'{indent}    strict=True\n'
        f'{indent})\n'
    )
    return content[:start_idx] + decorator + content[start_idx:]

def _detect_api_bug(test_name: str, traceback: str, original_test: str) -> tuple[bool, str]:
    """Deterministically detect API_BUGs according to the core testing rules."""
    # Rule 1: Server Crashes (500 / 5xx) where test expected 2xx/4xx
    if ("500" in traceback or "Internal Server Error" in traceback):
        if not ("assert response.status_code == 500" in original_test or "assert 500" in original_test):
            return True, "Server returned 500 Internal Server Error (unhandled server crash)"

    # Rule 2: Silent Data Corruption (server accepted payload with 200/201 but corrupted fields)
    if ("assert 0.0 == 0.1" in traceback or "assert 0 ==" in traceback or "assert 0.0 ==" in traceback or
        (("price" in traceback.lower() or "price" in original_test.lower()) and "assert 0" in traceback)):
        return True, "Server accepted payload but returned mutated/corrupted data (price field reset to 0.0)"

    if ("AssertionError" in traceback and
        ("response.json()[\"price\"]" in traceback or "response.json()['price']" in traceback or
         "payload[\"price\"]" in traceback or "payload['price']" in traceback)):
        return True, "Server accepted payload but returned mutated/corrupted data"

    # Contract violation: HTTP 200 returned when spec requires HTTP 204
    if "assert 200 == 204" in traceback or ("200 == 204" in traceback and "delete" in test_name.lower()):
        return True, "Server returned HTTP 200 instead of spec-mandated HTTP 204 No Content"

    return False, ""

def _infer_endpoint(test_name: str, nodeid: str, endpoints: list) -> str:
    """Extract clean endpoint path from test name, nodeid, or parsed endpoints."""
    combined = f"{nodeid} {test_name}".lower()
    for ep in endpoints:
        clean_path = ep["path"].strip("/").replace("/", "_").replace("{", "").replace("}", "").lower()
        if clean_path and clean_path in combined:
            return f"{ep['method'].upper()} {ep['path']}"
        op_id = ep.get("operation_id", "").lower()
        if op_id and op_id in combined:
            return f"{ep['method'].upper()} {ep['path']}"

    # Semantic heuristics based on test name
    if "create_item" in combined:
        return "POST /items/"
    if "get_item" in combined:
        return "GET /items/{item_id}"
    if "delete_item" in combined:
        return "DELETE /items/{item_id}"
    if "update_item" in combined:
        return "PUT /items/{item_id}"
    if "list_item" in combined:
        return "GET /items/"
    if "login" in combined or "token" in combined:
        return "POST /auth/token"
    if "register" in combined:
        return "POST /auth/register"
    if "journey" in combined or "smoke" in combined or "playwright" in combined or "e2e" in combined:
        return "E2E User Journey"

    return test_name.replace("test_", "").replace("_", " ").title()

def _is_e2e(item: dict) -> bool:
    """Check if a test or failure belongs to the Playwright E2E suite."""
    nid = item.get("nodeid", "").lower()
    tname = item.get("test_name", "").lower()
    return "playwright" in nid or "e2e" in nid or "journey" in tname or "smoke" in tname

def _replace_function(content: str, test_name: str, new_code: str) -> str:
    """Replace a function (and its decorators) using a safe line-scanner — no catastrophic-backtracking regex."""
    lines = content.splitlines(keepends=True)

    # Step 1: Find the def line (simple linear scan; one-line match only)
    def_line_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if re.match(rf"(?:async\s+)?def\s+{re.escape(test_name)}\s*\(", stripped):
            def_line_idx = i
            break
    if def_line_idx is None:
        return content  # function not found

    base_indent_len = len(lines[def_line_idx]) - len(lines[def_line_idx].lstrip(" \t"))

    # Step 2: Walk backwards to include consecutive decorator lines
    start_line_idx = def_line_idx
    for i in range(def_line_idx - 1, -1, -1):
        s = lines[i].strip()
        cur_indent = len(lines[i]) - len(lines[i].lstrip(" \t"))
        if s.startswith("@") and cur_indent == base_indent_len:
            start_line_idx = i
        elif s == "":
            # blank line breaks decorator chain
            break
        else:
            break

    # Step 3: Walk forward past the signature (until ":"), then past the body
    in_signature = True
    end_line_idx = def_line_idx + 1
    for i in range(def_line_idx, len(lines)):
        end_line_idx = i + 1
        if in_signature:
            # A colon that is not inside a comment ends the signature
            stripped_sig = lines[i].strip()
            if stripped_sig and ":" in stripped_sig and not stripped_sig.startswith("#"):
                in_signature = False
            continue
        s = lines[i].strip()
        if not s:
            continue  # skip blank lines inside body
        line_indent = len(lines[i]) - len(lines[i].lstrip(" \t"))
        if line_indent <= base_indent_len:
            end_line_idx = i
            break

    # Step 4: Re-indent new_code to match base_indent
    nc_lines = new_code.splitlines(keepends=False)
    non_empty = [l for l in nc_lines if l.strip()]
    if non_empty:
        code_indent = len(non_empty[0]) - len(non_empty[0].lstrip(" \t"))
        diff = base_indent_len - code_indent
        if diff > 0:
            pad = " " * diff
            nc_lines = [(pad + l) if l.strip() else l for l in nc_lines]
        elif diff < 0:
            dedent = -diff
            nc_lines = [
                l[dedent:] if l.startswith(" " * dedent) else l.lstrip(" \t")
                for l in nc_lines
            ]
    patched = "\n".join(nc_lines)
    if not patched.endswith("\n"):
        patched += "\n"

    print(
        f"  [healer] Replacing function {test_name} in source "
        f"(lines {start_line_idx + 1}–{end_line_idx})...",
        flush=True,
    )
    return "".join(lines[:start_line_idx]) + patched + "".join(lines[end_line_idx:])

# ==========================================
# NODE 1: parse_spec_node
# ==========================================
def parse_spec_node(state: AgentState) -> dict:
    """Fetch and parse the OpenAPI spec from the target API."""
    url = state["target_api_url"]
    openapi_url = f"{url.rstrip('/')}/openapi.json"
    
    try:
        endpoints = parse_spec(openapi_url)
        endpoints_serialized = [
            {
                "path": ep.path,
                "method": ep.method,
                "operation_id": ep.operation_id,
                "summary": ep.summary,
                "tags": ep.tags,
                "requires_auth": ep.requires_auth,
                "path_params": ep.path_params,
                "query_params": ep.query_params,
                "request_body": ep.request_body,
                "content_type": ep.content_type,
                "request_content_type": ep.request_content_type,
                "responses": ep.responses,
                "success_status_code": ep.success_status_code,
            }
            for ep in endpoints
        ]
        return {
            "endpoints": endpoints_serialized,
            "messages": [f"[parser] Parsed {len(endpoints)} endpoints from {openapi_url}"],
        }
    except Exception as e:
        return {
            "error": f"Failed to parse OpenAPI spec: {e}",
            "messages": [f"[parser] ERROR: {e}"],
        }

# ==========================================
# NODE 2: plan_node
# ==========================================
def plan_node(state: AgentState) -> dict:
    """Plan which tests to generate based on parsed endpoints."""
    endpoints = state.get("endpoints", [])
    plan_summary = []
    for ep in endpoints:
        plan_summary.append(
            f"  - {ep['method'].upper()} {ep['path']} "
            f"(auth={ep['requires_auth']}, success={ep['success_status_code']})"
        )
    plan_text = "Test plan:\n" + "\n".join(plan_summary)
    return {
        "messages": [f"[planner] {plan_text}"],
        "iteration": 0,
    }

# ==========================================
# NODE 3: generate_unit_tests_node
# ==========================================
def generate_unit_tests_node(state: AgentState) -> dict:
    """Generate pytest unit tests per endpoint using Ollama (chunked per endpoint)."""
    llm = get_llm()
    endpoints = state.get("endpoints", [])
    
    test_functions = []
    
    for idx, ep in enumerate(endpoints, 1):
        example_payload = {}
        if ep.get("request_body"):
            # The parser stores the schema directly under request_body (already extracted)
            example_payload = generate_example_payload(ep["request_body"])

        # Get primary response schema
        success_code = str(ep.get("success_status_code", 200))
        response_schema = ep.get("responses", {}).get(success_code, {})
        content_type = ep.get("content_type", ep.get("request_content_type", "application/json"))
        
        path_param_val = ""
        if ep.get("path_params") and len(ep["path_params"]) > 0:
            path_param_val = ep["path_params"][0].get("name", "")

        prompt = UNIT_TEST_TEMPLATE.format(
            method=ep["method"].upper(),
            path=ep["path"],
            operation_id=ep["operation_id"],
            requires_auth=ep["requires_auth"],
            success_status_code=ep["success_status_code"],
            content_type=content_type,
            request_body=json.dumps(ep.get("request_body"), indent=2)[:500],
            path_params=json.dumps(ep.get("path_params", []))[:200],
            path_param=path_param_val,
            response_schema=json.dumps(response_schema)[:400],
            example_payload=json.dumps(example_payload)[:300],
        )
        
        print(f"  [unit_generator] Generating tests {idx}/{len(endpoints)}: {ep['method'].upper()} {ep['path']}...", flush=True)
        try:
            response = llm.invoke([
                SystemMessage(content=UNIT_TEST_SYSTEM),
                HumanMessage(content=prompt),
            ])
            code = _extract_code_block(response.content)
        except (TimeoutError, Exception) as exc:
            print(f"  [unit_generator] WARNING: LLM request failed/timed out for {ep['method'].upper()} {ep['path']} ({exc}); skipping.", flush=True)
            continue

        # Content-type precision guard: ensure json= vs data= strictly aligns with OpenAPI spec
        if ep["path"] == "/auth/register":
            code = re.sub(r'client\.post\((\s*["\']/auth/register["\']\s*,\s*)data=', r'client.post(\1json=', code)
        elif ep["path"] == "/auth/token":
            code = re.sub(r'client\.post\((\s*["\']/auth/token["\']\s*,\s*)json=', r'client.post(\1data=', code)
        elif ep.get("content_type") == "application/json":
            code = re.sub(r'client\.(post|put)\((\s*["\'][^"\']+["\']\s*,\s*)data=', r'client.\1(\2json=', code)

        test_functions.append(f"\n# Tests for {ep['method'].upper()} {ep['path']}\n{code}")
    
    full_unit_test_file = (
        "\"\"\"Auto-generated unit tests for the target API.\"\"\"\n"
        "import pytest\n"
        "import httpx\n"
        "import uuid\n\n"
        + "\n".join(test_functions)
    )
    
    return {
        "generated_unit_tests": full_unit_test_file,
        "messages": [f"[unit_generator] Generated unit tests for {len(endpoints)} endpoints"],
    }

# ==========================================
# NODE 4: generate_e2e_tests_node
# ==========================================
def generate_e2e_tests_node(state: AgentState) -> dict:
    """Generate Playwright E2E tests for stateful user journeys."""
    llm = get_llm()
    base_url = state["target_api_url"]
    endpoints = state.get("endpoints", [])
    
    # Build endpoint schemas summary (token-efficient)
    ep_summary = {
        f"{ep['method'].upper()} {ep['path']}": {
            "success": ep["success_status_code"],
            "auth": ep["requires_auth"],
            "body": ep.get("request_body"),
        }
        for ep in endpoints
    }
    
    # Journey: Register -> Login -> CRUD flow
    steps = [
        "1. POST /auth/register with valid credentials → expect 201",
        "2. POST /auth/token with same credentials (form) → expect 200, save token",
        "3. POST /items/ with auth header → expect 201, save item_id",
        "4. GET /items/{item_id} with auth → expect 200, verify data",
        "5. PUT /items/{item_id} with auth → expect 200, verify updated data",
        "6. DELETE /items/{item_id} with auth → expect 204",
        "7. GET /items/{item_id} after delete → expect 404 OR 500 (note if 500: possible API_BUG)",
    ]
    
    prompt = E2E_TEMPLATE.format(
        journey_name="full_user_journey",
        steps="\n".join(steps),
        base_url=base_url,
        endpoint_schemas=json.dumps(ep_summary, indent=2)[:1000],
    )
    
    print("  [e2e_generator] Generating Playwright E2E journey tests...", flush=True)
    try:
        response = llm.invoke([
            SystemMessage(content=E2E_SYSTEM),
            HumanMessage(content=prompt),
        ])
        e2e_code = _extract_code_block(response.content)
    except (TimeoutError, Exception) as exc:
        print(f"  [e2e_generator] WARNING: LLM request failed/timed out for E2E tests ({exc}); skipping.", flush=True)
        e2e_code = ""
    
    full_e2e_file = (
        '"""Auto-generated Playwright E2E tests for stateful user journeys."""\n'
        "import pytest\n"
        "import uuid\n"
        "from playwright.sync_api import APIRequestContext, Page\n\n"
        + e2e_code
    )
    
    return {
        "generated_e2e_tests": full_e2e_file,
        "messages": ["[e2e_generator] Generated Playwright E2E tests"],
    }

# ==========================================
# NODE 5: write_tests_node
# ==========================================
def write_tests_node(state: AgentState) -> dict:
    """Write generated (or healed) tests to disk in generated_tests/."""
    GENERATED_TESTS_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    base_url = state["target_api_url"]

    # Build a static conftest.py from the template (no LLM call needed; saves tokens)
    conftest_code = f'''"""pytest conftest.py — generated by Autonomous API Testing Agent."""
import uuid
import pytest
import httpx

@pytest.fixture(scope="session")
def base_url() -> str:
    import os
    return os.getenv("TARGET_API_URL", "{base_url}")

@pytest.fixture(scope="session")
def client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        yield c

@pytest.fixture(scope="session")
def unique_username() -> str:
    return f"testuser_{{uuid.uuid4().hex[:8]}}"

@pytest.fixture(scope="session")
def registered_user(client: httpx.Client, unique_username: str) -> dict:
    payload = {{"username": unique_username, "password": "testpassword123"}}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201, f"Registration failed: {{response.status_code}} {{response.text}}"
    return {{"username": unique_username, "password": "testpassword123"}}

@pytest.fixture(scope="session")
def auth_token(client: httpx.Client, registered_user: dict) -> str:
    response = client.post(
        "/auth/token",
        data={{"username": registered_user["username"], "password": registered_user["password"]}},
        headers={{"Content-Type": "application/x-www-form-urlencoded"}},
    )
    assert response.status_code == 200, f"Login failed: {{response.status_code}} {{response.text}}"
    return response.json()["access_token"]

@pytest.fixture(scope="function")
def auth_headers(auth_token: str) -> dict:
    return {{"Authorization": f"Bearer {{auth_token}}"}}

@pytest.fixture(scope="session")
def playwright_base_url(base_url: str) -> str:
    return base_url
'''

    # Use healed versions if available, otherwise use generated
    unit_tests = state.get("healed_unit_tests") or state.get("generated_unit_tests", "")
    e2e_tests = state.get("healed_e2e_tests") or state.get("generated_e2e_tests", "")

    # Write files
    (GENERATED_TESTS_DIR / "conftest.py").write_text(conftest_code, encoding="utf-8")
    (GENERATED_TESTS_DIR / "test_unit_endpoints.py").write_text(unit_tests, encoding="utf-8")
    (GENERATED_TESTS_DIR / "test_e2e_playwright.py").write_text(e2e_tests, encoding="utf-8")

    return {
        "generated_conftest": conftest_code,
        "messages": [f"[writer] Wrote tests to {GENERATED_TESTS_DIR}/"],
    }

# ==========================================
# NODE 6: execute_tests_node
# ==========================================
def execute_tests_node(state: AgentState) -> dict:
    """Execute tests via the sandbox runner and parse results."""
    from src.sandbox.runner import run_tests_in_sandbox

    iteration = state.get("iteration", 0)
    # Respect --local flag set via SANDBOX_MODE env var
    mode = os.getenv("SANDBOX_MODE", "docker")
    result = run_tests_in_sandbox(mode=mode)

    test_results = result.get("test_results", [])
    passed = result.get("passed", 0)
    failed = result.get("failed", 0)
    total = len(test_results) if test_results else (passed + failed)

    update: Dict[str, Any] = {
        "test_results": test_results,
        "unit_test_failures": result.get("unit_failures", []),
        "e2e_test_failures": result.get("e2e_failures", []),
        "all_passed": result.get("all_passed", False),
        "messages": [
            f"[executor] Iteration {iteration} (mode={mode}): "
            f"{passed} passed, {failed} failed"
        ],
    }

    # Record Iteration 0 baseline metrics so they are never overwritten
    if iteration == 0 or state.get("zero_shot_passed") is None:
        update["zero_shot_passed"] = passed
        update["zero_shot_total"] = total

    return update

# ==========================================
# NODE 7: classify_failures_node
# ==========================================
def classify_failures_node(state: AgentState) -> dict:
    """Classify failures as TEST_BUG or API_BUG using the OpenAPI spec as ground truth."""
    all_failures = (
        state.get("unit_test_failures", []) + state.get("e2e_test_failures", [])
    )
    
    if not all_failures:
        return {"messages": ["[classifier] No failures to classify."]}
    
    llm = get_llm()
    endpoints = state.get("endpoints", [])
    
    classified = []
    api_bugs = []
    
    total_failures = len(all_failures)
    for i, failure in enumerate(all_failures):
        test_name = failure.get("test_name", "unknown")
        raw_traceback = failure.get("traceback", "")
        short_traceback = _truncate_traceback(raw_traceback, max_lines=20)
        nodeid = failure.get("nodeid", "")
        original_test = failure.get("test_source", "# test source not available")
        
        print(f"  [healer] Analyzing failure {i+1}/{total_failures}: {test_name}...", flush=True)

        # Check deterministic classification rules first (against full raw traceback)
        is_api_bug, rule_reason = _detect_api_bug(test_name, raw_traceback, original_test)
        
        if is_api_bug:
            failure_type = "API_BUG"
            reason = rule_reason
            fixed_code = ""
            print(f"  [healer]   -> Classified as API_BUG (rule): {reason}", flush=True)
        else:
            # Find relevant endpoint spec
            relevant_ep = None
            for ep in endpoints:
                if ep["path"].replace("/", "_").strip("_") in test_name or \
                   ep["operation_id"] in test_name:
                    relevant_ep = ep
                    break
            
            ep_spec = json.dumps(relevant_ep, indent=2)[:800] if relevant_ep else "{}"
            
            prompt = HEAL_TEMPLATE.format(
                original_test=original_test[:800],
                traceback=short_traceback,
                endpoint_spec=ep_spec,
            )
            
            try:
                response = llm.invoke([
                    SystemMessage(content=HEAL_SYSTEM),
                    HumanMessage(content=prompt),
                ])
                classification, fixed_code = _extract_json_and_code(response.content)
                failure_type = classification.get("classification", "TEST_BUG")
                reason = classification.get("reason", "No reason provided")
            except (TimeoutError, Exception) as exc:
                print(
                    f"  [healer] WARNING: LLM call timed out/failed for {test_name} ({exc}); skipping patch.",
                    flush=True,
                )
                classified.append({
                    **failure,
                    "failure_type": "TEST_BUG",
                    "reason": f"Skipped due to LLM timeout/error: {exc}",
                    "fixed_code": "",
                })
                continue

        classified.append({
            **failure,
            "failure_type": failure_type,
            "reason": reason,
            "fixed_code": fixed_code,
        })
        
        if failure_type == "API_BUG":
            endpoint_name = _infer_endpoint(test_name, nodeid, endpoints)
            api_bugs.append({
                "test_name": test_name,
                "endpoint": endpoint_name,
                "reason": reason,
                "traceback": short_traceback,
            })
    
    # Separate back into unit vs e2e using nodeid / test name
    unit_failures = [f for f in classified if not _is_e2e(f)]
    e2e_failures = [f for f in classified if _is_e2e(f)]
    
    existing_bug_tests = {b.get("test_name") for b in state.get("bug_reports", [])}
    new_bugs = [b for b in api_bugs if b.get("test_name") not in existing_bug_tests]
    bug_reports = state.get("bug_reports", []) + new_bugs
    
    return {
        "unit_test_failures": unit_failures,
        "e2e_test_failures": e2e_failures,
        "bug_reports": bug_reports,
        "messages": [
            f"[classifier] Classified {len(classified)} failures: "
            f"{len(api_bugs)} API bugs, {len(classified)-len(api_bugs)} test bugs"
        ],
    }

# ==========================================
# NODE 8: heal_tests_node
# ==========================================
def heal_tests_node(state: AgentState) -> dict:
    """Rewrite failing tests (TEST_BUG) or decorate API_BUGs with xfail."""
    unit_failures = state.get("unit_test_failures", [])
    e2e_failures = state.get("e2e_test_failures", [])
    
    unit_tests = state.get("healed_unit_tests") or state.get("generated_unit_tests", "")
    e2e_tests = state.get("healed_e2e_tests") or state.get("generated_e2e_tests", "")

    if not unit_tests and (GENERATED_TESTS_DIR / "test_unit_endpoints.py").exists():
        unit_tests = (GENERATED_TESTS_DIR / "test_unit_endpoints.py").read_text(encoding="utf-8")
    if not e2e_tests and (GENERATED_TESTS_DIR / "test_e2e_playwright.py").exists():
        e2e_tests = (GENERATED_TESTS_DIR / "test_e2e_playwright.py").read_text(encoding="utf-8")
    
    def apply_fixes(test_content: str, failures: list, suite_label: str) -> str:
        total = len(failures)
        for i, failure in enumerate(failures):
            failure_type = failure.get("failure_type", "TEST_BUG")
            test_name = failure.get("test_name", "")
            fixed_code = failure.get("fixed_code", "")
            reason = failure.get("reason", "")
            
            if not test_name:
                continue

            print(
                f"  [healer] Patching {suite_label} test {i+1}/{total}: {test_name} ({failure_type})...",
                flush=True,
            )

            try:
                if failure_type == "API_BUG":
                    test_content = _add_xfail_decorator(test_content, test_name, reason)
                elif failure_type == "TEST_BUG" and fixed_code:
                    clean_code = fixed_code.strip()
                    # Skip invalid JSON or non-code injections
                    if clean_code.startswith("{") or clean_code.startswith("json\n") or clean_code.startswith("json\r\n"):
                        print(f"  [healer]   WARNING: Skipping non-Python patch for {test_name}.", flush=True)
                        continue
                    if "def " not in clean_code:
                        print(f"  [healer]   WARNING: Patch missing function def for {test_name}; skipping.", flush=True)
                        continue
                    # Validate syntax of isolated replacement function
                    try:
                        ast.parse(textwrap.dedent(clean_code))
                    except Exception as syn_err:
                        print(f"  [healer]   WARNING: Patch syntax error for {test_name} ({syn_err}); skipping.", flush=True)
                        continue
                    
                    candidate = _replace_function(test_content, test_name, clean_code)
                    # Ensure the entire file still parses cleanly
                    try:
                        ast.parse(candidate)
                        test_content = candidate
                    except Exception as file_err:
                        print(f"  [healer]   WARNING: Merged AST invalid for {test_name} ({file_err}); keeping original.", flush=True)
                elif failure_type == "TEST_BUG" and not fixed_code:
                    print(f"  [healer]   WARNING: No patch code produced for {test_name}; skipping.", flush=True)
            except (TimeoutError, Exception) as exc:
                print(f"  [healer]   WARNING: Unexpected error patching {test_name} ({exc}); skipping.", flush=True)
                continue
        
        return test_content
    
    healed_unit = apply_fixes(unit_tests, unit_failures, "unit")
    healed_e2e = apply_fixes(e2e_tests, e2e_failures, "E2E")

    # Safety guard: ensure healed contents are always valid Python AST
    try:
        ast.parse(healed_unit)
    except Exception:
        healed_unit = unit_tests
    try:
        ast.parse(healed_e2e)
    except Exception:
        healed_e2e = e2e_tests
    
    new_iteration = state.get("iteration", 0) + 1
    
    return {
        "healed_unit_tests": healed_unit,
        "healed_e2e_tests": healed_e2e,
        "iteration": new_iteration,
        "messages": [
            f"[healer] Iteration {new_iteration}: Applied fixes to "
            f"{len(unit_failures)} unit failures, {len(e2e_failures)} E2E failures"
        ],
    }

# ==========================================
# NODE 9: metrics_node
# ==========================================
def metrics_node(state: AgentState) -> dict:
    """Calculate and write final metrics and bug report."""
    import datetime
    
    test_results = state.get("test_results", [])
    total = len(test_results)
    passed = sum(1 for r in test_results if r.get("status") == "passed")
    failed = sum(1 for r in test_results if r.get("status") == "failed")
    xfailed = sum(1 for r in test_results if r.get("status") == "xfail")
    
    # Retrieve iteration 0 stats
    zero_shot_pass = state.get("zero_shot_passed")
    zero_shot_total = state.get("zero_shot_total")
    if zero_shot_pass is None or zero_shot_total is None:
        zero_shot_pass = passed
        zero_shot_total = total or 1

    zero_shot_rate = round(zero_shot_pass / zero_shot_total, 3) if zero_shot_total else 0.0
    post_healing_rate = round((passed + xfailed) / total, 3) if total else 0.0

    metrics = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "xfailed_api_bugs": xfailed,
        "zero_shot_pass_rate": zero_shot_rate,
        "post_healing_pass_rate": post_healing_rate,
        "api_bugs_caught": len(state.get("bug_reports", [])),
        "healing_iterations": state.get("iteration", 0),
    }
    
    REPORTS_DIR.mkdir(exist_ok=True)
    
    # Write metrics.json
    metrics_path = REPORTS_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    
    # Write bug_report.md
    bug_reports = state.get("bug_reports", [])
    bug_md_lines = [
        "# API Bug Report",
        f"",
        f"Generated: {metrics['timestamp']}",
        f"",
        f"## Summary",
        f"- Total API bugs caught: **{len(bug_reports)}**",
        f"- These tests are marked `@pytest.mark.xfail(strict=True)` and will FAIL if the bug is fixed without updating the decorator.",
        f"",
        f"## Detected Bugs",
        f"",
    ]
    for i, bug in enumerate(bug_reports, 1):
        bug_md_lines += [
            f"### Bug #{i}: {bug.get('endpoint', 'unknown')}",
            f"- **Test:** `{bug.get('test_name', 'N/A')}`",
            f"- **Reason:** {bug.get('reason', 'N/A')}",
            f"- **Traceback excerpt:**",
            f"```",
            (bug.get("traceback", "N/A") or "N/A")[:500],
            f"```",
            f"",
        ]
    
    bug_report_path = REPORTS_DIR / "bug_report.md"
    bug_report_path.write_text("\n".join(bug_md_lines), encoding="utf-8")
    
    return {
        "metrics": metrics,
        "messages": [
            f"[metrics] Final: {passed}/{total} passed, "
            f"{len(bug_reports)} API bugs caught. "
            f"Zero-shot pass rate: {metrics['zero_shot_pass_rate']:.1%}, "
            f"Post-healing: {metrics['post_healing_pass_rate']:.1%}"
        ],
    }
