"""
Sandbox runner: executes pytest inside Docker and parses JUnit XML / JSON output.
Two modes:
  1. Docker mode (default): spins up docker compose, runs sandbox_runner container
  2. Local mode (fallback, --local flag): runs pytest directly in subprocess
"""
import os
import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional

GENERATED_TESTS_DIR = Path("generated_tests")
REPORTS_DIR = Path("reports")
DOCKER_COMPOSE_FILE = Path("docker/docker-compose.yml")

def run_tests_in_sandbox(mode: str = "docker", timeout: int = 300) -> Dict[str, Any]:
    """
    Execute the test suite and return parsed results.
    
    Returns:
        {
            "passed": int,
            "failed": int,
            "errors": int,
            "all_passed": bool,
            "test_results": List[TestResult],
            "unit_failures": List[dict],
            "e2e_failures": List[dict],
            "raw_output": str,
        }
    """
    if mode == "docker" and _docker_available():
        return _run_docker(timeout=timeout)
    else:
        return _run_local(timeout=timeout)

def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def _run_docker(timeout: int = 300) -> Dict[str, Any]:
    """Run tests via docker compose."""
    # Ensure reports dir exists on host
    REPORTS_DIR.mkdir(exist_ok=True)
    
    # First build the images
    build_result = subprocess.run(
        ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), "build"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    if build_result.returncode != 0:
        return _error_result(f"Docker build failed:\n{build_result.stderr}")
    
    # Run sandbox_runner with the runner profile
    run_result = subprocess.run(
        [
            "docker", "compose",
            "-f", str(DOCKER_COMPOSE_FILE),
            "--profile", "runner",
            "up",
            "--abort-on-container-exit",
            "--exit-code-from", "sandbox_runner",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    
    raw_output = run_result.stdout + run_result.stderr
    
    # Try to parse JSON report (written to reports/report.json by pytest-json-report)
    report_path = REPORTS_DIR / "report.json"
    if report_path.exists():
        return _parse_json_report(report_path, raw_output)
    
    # Fallback: parse pytest output text
    return _parse_pytest_output(raw_output)

def _run_local(timeout: int = 120) -> Dict[str, Any]:
    """Run tests directly with pytest (local fallback, no Docker)."""
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / "report.json"
    
    result = subprocess.run(
        [
            "pytest",
            str(GENERATED_TESTS_DIR),
            "-p", "no:asyncio",
            "--tb=short",
            "--json-report",
            f"--json-report-file={report_path}",
            "-v",
            "--ignore", str(GENERATED_TESTS_DIR / "reports"),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    
    raw_output = result.stdout + result.stderr
    
    if report_path.exists():
        return _parse_json_report(report_path, raw_output)
    
    return _parse_pytest_output(raw_output)

def _parse_json_report(report_path: Path, raw_output: str) -> Dict[str, Any]:
    """Parse pytest-json-report output into our standard result format."""
    with open(report_path) as f:
        report = json.load(f)
    
    summary = report.get("summary", {})
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    errors = summary.get("error", 0)
    
    test_results = []
    unit_failures = []
    e2e_failures = []
    
    for test in report.get("tests", []):
        test_name = test.get("nodeid", "unknown").split("::")[-1]
        outcome = test.get("outcome", "unknown")
        
        # Map pytest outcomes
        status = {
            "passed": "passed",
            "failed": "failed",
            "xfailed": "xfail",
            "xpassed": "xpass",
            "error": "error",
            "skipped": "skipped",
        }.get(outcome, outcome)
        
        # Get traceback (check call, then setup, then teardown; keep tail with actual error/assertion)
        traceback = ""
        for phase in ("call", "setup", "teardown"):
            phase_info = test.get(phase, {})
            if phase_info and phase_info.get("longrepr"):
                raw_tb = str(phase_info["longrepr"])
                tb_lines = raw_tb.strip().splitlines()
                traceback = "\n".join(tb_lines[-25:]) if len(tb_lines) > 25 else raw_tb
                break
        
        # Get test source (for healing context)
        test_source = _get_test_source(test.get("nodeid", ""))
        
        result_entry = {
            "test_name": test_name,
            "nodeid": test.get("nodeid", ""),
            "status": status,
            "traceback": traceback,
            "test_source": test_source,
            "failure_type": None,
            "heal_action": None,
        }
        
        test_results.append(result_entry)
        
        if status in ("failed", "error"):
            if "playwright" in test.get("nodeid", "").lower() or \
               "e2e" in test.get("nodeid", "").lower():
                e2e_failures.append(result_entry)
            else:
                unit_failures.append(result_entry)

    # Capture collection errors from collectors (e.g. syntax errors during import)
    for collector in report.get("collectors", []):
        c_outcome = collector.get("outcome", "")
        if c_outcome in ("failed", "error"):
            c_nodeid = collector.get("nodeid", "collection_error")
            c_tb = str(collector.get("longrepr", ""))[:2000]
            c_name = c_nodeid.split("/")[-1].replace(".py", "") or "collection_error"
            collector_entry = {
                "test_name": c_name,
                "nodeid": c_nodeid,
                "status": "error",
                "traceback": c_tb,
                "test_source": "",
                "failure_type": "TEST_BUG",
                "heal_action": None,
            }
            test_results.append(collector_entry)
            errors += 1
            if "playwright" in c_nodeid.lower() or "e2e" in c_nodeid.lower():
                e2e_failures.append(collector_entry)
            else:
                unit_failures.append(collector_entry)

    # If pytest exited with an error code and no test was collected or ran
    exit_code = report.get("exitcode", 0)
    if exit_code != 0 and (passed + failed + errors) == 0:
        errors += 1
        startup_entry = {
            "test_name": "pytest_execution_error",
            "nodeid": "pytest",
            "status": "error",
            "traceback": raw_output[:2000],
            "test_source": "",
            "failure_type": "TEST_BUG",
            "heal_action": None,
        }
        test_results.append(startup_entry)
        unit_failures.append(startup_entry)

    total_failed = failed + errors
    all_passed = (total_failed == 0) and (passed > 0)
    
    return {
        "passed": passed,
        "failed": total_failed,
        "errors": errors,
        "all_passed": all_passed,
        "test_results": test_results,
        "unit_failures": unit_failures,
        "e2e_failures": e2e_failures,
        "raw_output": raw_output,
    }

def _parse_pytest_output(raw_output: str) -> Dict[str, Any]:
    """Fallback parser for plain pytest text output."""
    lines = raw_output.split("\n")
    passed = failed = errors = 0
    
    for line in lines:
        if "passed" in line and ("=" in line or "-" in line):
            import re
            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+) error", line)
            if m:
                errors = int(m.group(1))

    total_failed = failed + errors
    all_passed = (total_failed == 0) and (passed > 0)
    
    return {
        "passed": passed,
        "failed": total_failed,
        "errors": errors,
        "all_passed": all_passed,
        "test_results": [],
        "unit_failures": [],
        "e2e_failures": [],
        "raw_output": raw_output,
    }

def _get_test_source(nodeid: str) -> str:
    """Read the source of a test function from the generated test file."""
    try:
        parts = nodeid.split("::")
        if len(parts) < 2:
            return ""
        file_path = GENERATED_TESTS_DIR / parts[0].replace("generated_tests/", "")
        if not file_path.exists():
            return ""
        source = file_path.read_text(encoding="utf-8")
        func_name = parts[-1]
        import re
        all_lines = source.splitlines(keepends=True)

        # Step 1: find the def line with a safe per-line match (no body regex)
        def_line_idx = None
        for i, line in enumerate(all_lines):
            if re.match(rf"(?:async\s+)?def\s+{re.escape(func_name)}\s*\(", line.lstrip()):
                def_line_idx = i
                break
        if def_line_idx is None:
            return source[:500]

        base_indent_len = len(all_lines[def_line_idx]) - len(all_lines[def_line_idx].lstrip(" \t"))

        # Step 2: walk backwards to include decorator lines at the same indent
        start_line_idx = def_line_idx
        for i in range(def_line_idx - 1, -1, -1):
            s = all_lines[i].strip()
            cur_indent = len(all_lines[i]) - len(all_lines[i].lstrip(" \t"))
            if s.startswith("@") and cur_indent == base_indent_len:
                start_line_idx = i
            elif s == "":
                break
            else:
                break

        # Step 3: walk forward past the signature then past the body
        in_sig = True
        end_line_idx = def_line_idx + 1
        for i in range(def_line_idx, len(all_lines)):
            end_line_idx = i + 1
            if in_sig:
                stripped_sig = all_lines[i].strip()
                if stripped_sig and ":" in stripped_sig and not stripped_sig.startswith("#"):
                    in_sig = False
                continue
            s = all_lines[i].strip()
            if not s:
                continue
            line_indent = len(all_lines[i]) - len(all_lines[i].lstrip(" \t"))
            if line_indent <= base_indent_len:
                end_line_idx = i
                break

        extracted = "".join(all_lines[start_line_idx:end_line_idx])
        return extracted[:1500]
    except Exception:
        return ""

def _error_result(msg: str) -> Dict[str, Any]:
    return {
        "passed": 0,
        "failed": 1,
        "errors": 1,
        "all_passed": False,
        "test_results": [],
        "unit_failures": [{"test_name": "sandbox_startup", "traceback": msg, "test_source": ""}],
        "e2e_failures": [],
        "raw_output": msg,
    }
