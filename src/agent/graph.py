"""LangGraph StateGraph definition for the autonomous testing agent."""
from langgraph.graph import StateGraph, END
from src.agent.state import AgentState

def should_heal_or_finish(state: AgentState) -> str:
    """Conditional edge: decide whether to heal, finish, or report bugs."""
    if state.get("all_passed"):
        return "metrics"
    if state.get("iteration", 0) >= state.get("max_iterations", 3):
        return "metrics"  # max iterations reached, go to final metrics
    # Check if there are failures to heal
    failures = state.get("unit_test_failures", []) + state.get("e2e_test_failures", [])
    if failures:
        return "healer"
    return "metrics"

def build_graph() -> StateGraph:
    from src.agent.nodes import (
        parse_spec_node,
        plan_node,
        generate_unit_tests_node,
        generate_e2e_tests_node,
        write_tests_node,
        execute_tests_node,
        classify_failures_node,
        heal_tests_node,
        metrics_node,
    )
    
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("parser", parse_spec_node)
    graph.add_node("planner", plan_node)
    graph.add_node("unit_generator", generate_unit_tests_node)
    graph.add_node("e2e_generator", generate_e2e_tests_node)
    graph.add_node("writer", write_tests_node)
    graph.add_node("executor", execute_tests_node)
    graph.add_node("classifier", classify_failures_node)
    graph.add_node("healer", heal_tests_node)
    graph.add_node("metrics", metrics_node)
    
    # Edges
    graph.set_entry_point("parser")
    graph.add_edge("parser", "planner")
    graph.add_edge("planner", "unit_generator")
    graph.add_edge("unit_generator", "e2e_generator")
    graph.add_edge("e2e_generator", "writer")
    graph.add_edge("writer", "executor")
    graph.add_edge("executor", "classifier")
    graph.add_conditional_edges("classifier", should_heal_or_finish, {
        "healer": "healer",
        "metrics": "metrics",
    })
    graph.add_edge("healer", "writer")  # re-write healed tests, then re-execute
    graph.add_edge("metrics", END)
    
    return graph.compile()
