"""LangGraph conversation orchestration for the Realtime Voice API."""

from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from backend.tools import execute_tool, TOOL_DEFINITIONS


class ConversationState(TypedDict):
    """State for the voice conversation graph."""

    messages: Annotated[list, add_messages]
    pending_tool_calls: list[dict]
    tool_results: list[dict]
    current_phase: str


def should_route(state: ConversationState) -> Literal["process_tools", "wait_for_input"]:
    """Decide whether to process tool calls or wait for more input."""
    if state.get("pending_tool_calls"):
        return "process_tools"
    return "wait_for_input"


def process_tool_calls(state: ConversationState) -> ConversationState:
    """Process pending tool calls from the Realtime API."""
    results = []
    for tool_call in state.get("pending_tool_calls", []):
        name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", "{}")
        call_id = tool_call.get("call_id", "")

        result = execute_tool(name, arguments)
        results.append({
            "call_id": call_id,
            "name": name,
            "result": result,
        })

    return {
        **state,
        "pending_tool_calls": [],
        "tool_results": results,
        "current_phase": "tool_results_ready",
    }


def wait_for_input(state: ConversationState) -> ConversationState:
    """Wait state - conversation is idle waiting for user audio input."""
    return {
        **state,
        "current_phase": "waiting",
    }


def build_conversation_graph() -> StateGraph:
    """Build the LangGraph conversation state graph."""
    graph = StateGraph(ConversationState)

    # Add nodes
    graph.add_node("process_tools", process_tool_calls)
    graph.add_node("wait_for_input", wait_for_input)

    # Set entry point with conditional routing
    graph.set_conditional_entry_point(should_route)

    # Add edges
    graph.add_edge("process_tools", END)
    graph.add_edge("wait_for_input", END)

    return graph.compile()


# Compiled graph instance
conversation_graph = build_conversation_graph()


def get_tool_definitions() -> list[dict]:
    """Return the tool definitions for the Realtime API session configuration."""
    return TOOL_DEFINITIONS


def handle_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """
    Process tool calls through the LangGraph pipeline.

    Args:
        tool_calls: List of tool call dicts with 'name', 'arguments', 'call_id'

    Returns:
        List of tool result dicts with 'call_id', 'name', 'result'
    """
    initial_state: ConversationState = {
        "messages": [],
        "pending_tool_calls": tool_calls,
        "tool_results": [],
        "current_phase": "processing",
    }

    result = conversation_graph.invoke(initial_state)
    return result.get("tool_results", [])
