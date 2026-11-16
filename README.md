# Autonomous API Testing & Code Generation Agent 🤖⚡

An autonomous, black-box agentic testing pipeline built with **LangGraph**, local **Ollama** (`qwen2.5-coder:7b`), **Docker**, and **Playwright**. 

The agent ingests any target application's OpenAPI specification (`openapi.json`), deterministically parses contracts and dependencies, autonomously generates Pytest (API) and Playwright (E2E) suites, and continuously heals failing tests in a closed execution loop while isolating true server bugs.

---

## 🎯 Key Highlights & Architecture

- **Strict Black-Box Boundary:** The agent never inspects target source code. It relies exclusively on OpenAPI schemas, runtime HTTP status codes, and execution tracebacks.
- **Deterministic AST & Schema Resolution:** 
  - Resolves `$ref` schemas recursively to prevent LLM hallucinations.
  - Automatically identifies endpoint content types (e.g., distinguishing JSON endpoints from OAuth2 `application/x-www-form-urlencoded` forms).
  - Validates generated Python syntax via `ast.parse` prior to disk writes.
- **Stateful Failure Classification:**
  - `TEST_BUG`: Malformed payloads, assertion mistakes, or syntax issues $\rightarrow$ autonomously repaired via iterative LLM reflection (max 3 loops).
  - `API_BUG`: Undocumented $500$ crashes, status code contract breaches, or silent data corruption $\rightarrow$ quarantined using `@pytest.mark.xfail(strict=True)` and exported to markdown bug reports.

```
                    ┌─────────────────────────┐
                    │      OpenAPI Spec       │
                    │   (Target FastAPI)      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                     [Deterministic Parser]
                   (Resolves $ref & Mime Types)
                                 │
                                 ▼
                      [Planner & Generators]
                   (Pytest API & Playwright E2E)
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Docker Sandbox Run    │
                    │      (pytest-json)      │
                    └────────────┬────────────┘
                                 │
               ┌─────────────────┴─────────────────┐
               ▼                                   ▼
        [Pass / xfail]                         [Failures]
               │                                   │
               │                                   ▼
               │                          [Classifier Node]
               │                         (TEST_BUG vs API_BUG)
               │                                   │
               │                   ┌───────────────┴───────────────┐
               │                   ▼                               ▼
               │              [TEST_BUG]                       [API_BUG]
               │        (Self-Healing Loop)           (Strict xfail & Report)
               │                   │                               │
               │                   └───────► [Loop Back] ◄─────────┘
               ▼
     [Metrics & Bug Reports]
```

---

## 📊 Benchmark Results (Local Model Execution)

Evaluated against a benchmark FastAPI target running three deliberate server defects ($500$ KeyError crash, 204 contract violation, and silent price data corruption):

| Metric | Target / Result |
| :--- | :--- |
| **Orchestrator** | LangGraph Stateful Cyclic Graph |
| **Model** | Local `qwen2.5-coder:7b` via Ollama (Zero cloud dependencies) |
| **Zero-Shot Pass Rate** | **41.4%** (12 / 29 passed) |
| **Post-Healing Pass Rate** | **82.8%** (24 / 29 passed + isolated) |
| **Planted API Defects Caught** | **2 / 2** ($500$ Server Crash + Silent Data Corruption) |
| **Human Code Intervention** | **0 lines modified manually** |

---

## 📁 Repository Structure

```text
autonomous-api-testing-agent/
├── benchmark_app/               # Target FastAPI app with deliberate real-world bugs
│   ├── main.py
│   ├── models.py
│   └── Dockerfile.target
├── docker/
│   ├── Dockerfile.sandbox       # Sandboxed test execution runtime (Playwright + Pytest)
│   └── docker-compose.yml
├── src/
│   ├── parser/
│   │   └── openapi_parser.py    # Recursive $ref resolver & dependency builder
│   ├── agent/
│   │   ├── graph.py             # LangGraph state machine & conditional healing routing
│   │   ├── nodes.py             # Parser, Planner, Generators, Executor, Classifier, Healer
│   │   ├── prompts.py           # Few-shot token-optimized prompts
│   │   └── state.py             # AgentState TypedDict definition
│   └── sandbox/
│       └── runner.py            # Local and Docker execution runners
├── generated_tests/             # Autonomously written & healed tests
│   ├── conftest.py
│   ├── test_unit_endpoints.py
│   └── test_e2e_playwright.py
├── reports/
│   ├── bug_report.md            # Generated report detailing true server defects
│   └── metrics.json             # Execution metrics and healing delta
├── main.py                      # CLI entrypoint
└── requirements.txt
```

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11+
- Docker Desktop
- [Ollama](https://ollama.ai) installed with `qwen2.5-coder:7b`:
  ```bash
  ollama pull qwen2.5-coder:7b
  ```

### 2. Setup
```bash
git clone https://github.com/MajdSouissi/autonomous-api-testing-agent.git
cd autonomous-api-testing-agent
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Launch Target API & Run Pipeline
Start the target API inside Docker:
```bash
docker build -t target_api -f benchmark_app/Dockerfile.target .
docker run -d --name target_api -p 8000:8000 target_api
```

Run the autonomous agent:
```bash
python main.py --url http://localhost:8000 --local
```

Inspect reports:
```bash
cat reports/bug_report.md
cat reports/metrics.json
```