from typing import TypedDict, List, Optional, Dict, Any, Annotated
import operator

class TestResult(TypedDict):
    test_name: str
    status: str          # "passed", "failed", "error", "xfail"
    failure_type: Optional[str]  # "TEST_BUG" | "API_BUG" | None
    traceback: Optional[str]
    heal_action: Optional[str]   # description of what was patched

class AgentState(TypedDict):
    # Input
    target_api_url: str
    openapi_spec: Optional[Dict[str, Any]]
    endpoints: Optional[List[Dict[str, Any]]]  # serialized EndpointInfos
    
    # Generation
    generated_unit_tests: Optional[str]        # full pytest file content
    generated_e2e_tests: Optional[str]         # full pytest-playwright file content
    generated_conftest: Optional[str]          # conftest.py content
    
    # Execution & Healing
    iteration: int                              # current healing iteration (0=initial)
    max_iterations: int                         # default 3
    test_results: List[TestResult]
    unit_test_failures: List[Dict[str, Any]]
    e2e_test_failures: List[Dict[str, Any]]
    healed_unit_tests: Optional[str]
    healed_e2e_tests: Optional[str]
    
    # Outputs
    all_passed: bool
    bug_reports: List[Dict[str, Any]]           # API_BUG entries
    metrics: Dict[str, Any]
    
    # Control flow
    error: Optional[str]
    messages: Annotated[List[str], operator.add]  # append-only log
