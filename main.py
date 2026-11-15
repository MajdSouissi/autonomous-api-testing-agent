#!/usr/bin/env python3
"""
CLI entrypoint for the Autonomous API Testing & Code Generation Agent.

Usage:
    python main.py --url http://localhost:8000
    python main.py --url http://localhost:8000 --model qwen2.5-coder:7b --local
    python main.py --url http://localhost:8000 --iterations 5
"""
import argparse
import json
import os
import sys
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(
        description="Autonomous API Testing & Code Generation Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the target FastAPI application (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--model",
        default="qwen2.5-coder:7b",
        help="Ollama model to use (default: qwen2.5-coder:7b)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Maximum self-healing iterations (default: 3)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run tests locally (no Docker) — useful for development",
    )
    parser.add_argument(
        "--skip-e2e",
        action="store_true",
        help="Skip Playwright E2E tests (run only unit tests)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama server URL (default: http://localhost:11434)",
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Set environment variables for the nodes
    os.environ["OLLAMA_MODEL"] = args.model
    os.environ["OLLAMA_BASE_URL"] = args.ollama_url
    if args.local:
        os.environ["SANDBOX_MODE"] = "local"
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║   Autonomous API Testing & Code Generation Agent             ║
║   Target: {args.url:<50}║
║   Model:  {args.model:<50}║
║   Mode:   {'Local' if args.local else 'Docker':<50}║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Import here to allow env vars to be set first
    from src.agent.graph import build_graph
    
    graph = build_graph()
    
    initial_state = {
        "target_api_url": args.url,
        "openapi_spec": None,
        "endpoints": None,
        "generated_unit_tests": None,
        "generated_e2e_tests": None,
        "generated_conftest": None,
        "iteration": 0,
        "max_iterations": args.iterations,
        "test_results": [],
        "unit_test_failures": [],
        "e2e_test_failures": [],
        "healed_unit_tests": None,
        "healed_e2e_tests": None,
        "all_passed": False,
        "bug_reports": [],
        "metrics": {},
        "error": None,
        "messages": [],
    }
    
    print("🚀 Starting LangGraph pipeline...\n")
    
    # Stream graph execution with live logging
    final_state = None
    for event in graph.stream(initial_state, stream_mode="values"):
        final_state = event
        # Print latest log message
        messages = event.get("messages", [])
        if messages:
            print(f"  {messages[-1]}")
    
    if not final_state:
        print("❌ Pipeline failed — no final state.")
        sys.exit(1)
    
    if final_state.get("error"):
        print(f"\n❌ Pipeline error: {final_state['error']}")
        sys.exit(1)
    
    # Print final metrics
    metrics = final_state.get("metrics", {})
    bug_reports = final_state.get("bug_reports", [])
    
    zs_rate = f"{metrics.get('zero_shot_pass_rate', 0.0):.1%}"
    ph_rate = f"{metrics.get('post_healing_pass_rate', 0.0):.1%}"
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    FINAL RESULTS                             ║
╠══════════════════════════════════════════════════════════════╣
║  Total tests:          {metrics.get('total_tests', 0):<37}║
║  Passed:               {metrics.get('passed', 0):<37}║
║  Failed:               {metrics.get('failed', 0):<37}║
║  API Bugs (xfail):     {metrics.get('xfailed_api_bugs', 0):<37}║
║  Zero-shot pass rate:  {zs_rate:<37}║
║  Post-healing rate:    {ph_rate:<37}║
║  Healing iterations:   {metrics.get('healing_iterations', 0):<37}║
╠══════════════════════════════════════════════════════════════╣
║  API Bugs caught: {len(bug_reports):<43}║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    if bug_reports:
        print("🐛 API Bugs detected (see reports/bug_report.md):")
        for bug in bug_reports:
            print(f"  • {bug.get('endpoint')}: {bug.get('reason')}")
    
    print(f"\n📊 Metrics saved to: reports/metrics.json")
    print(f"📋 Bug report saved to: reports/bug_report.md")
    print(f"🧪 Generated tests in: generated_tests/")
    
    # Exit with non-zero if there are unhealed TEST_BUG failures
    remaining_failures = final_state.get("unit_test_failures", []) + \
                         final_state.get("e2e_test_failures", [])
    test_bug_failures = [f for f in remaining_failures if f.get("failure_type") == "TEST_BUG"]
    
    if test_bug_failures:
        print(f"\n⚠️  {len(test_bug_failures)} TEST_BUG failures remain after {args.iterations} iterations.")
        sys.exit(2)

if __name__ == "__main__":
    main()
