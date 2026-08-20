"""The agent's state machine.

Fixed outer skeleton, free inner execution: the sequence of nodes is always
guaranteed, while the decisions inside Execute are the model's.

    clarify -> plan -> execute -> reflect -> synthesize

The loop-back edge from reflect to execute arrives in Sprint 9 along with
confidence gating. Today reflect always continues to synthesize, so a run is a
single pass and is easy to reason about.
"""

from langgraph.graph import END, StateGraph

from agent.nodes import clarify, execute, plan, reflect, synthesize
from agent.state import AgentState


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("clarify", clarify)
    builder.add_node("plan", plan)
    builder.add_node("execute", execute)
    builder.add_node("reflect", reflect)
    builder.add_node("synthesize", synthesize)

    builder.set_entry_point("clarify")
    builder.add_edge("clarify", "plan")
    builder.add_edge("plan", "execute")
    builder.add_edge("execute", "reflect")
    builder.add_edge("reflect", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile()


graph = build_graph()
