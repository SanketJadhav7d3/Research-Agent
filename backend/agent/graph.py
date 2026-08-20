"""The agent's state machine.

Fixed outer skeleton, free inner execution: the sequence of nodes is always
guaranteed, while the decisions inside Execute are the model's.

    clarify -> plan -> execute -> reflect -> synthesize

Reflect does not always continue to synthesize. If it scores its own work
below the threshold and iterations remain, control returns to execute for
another round aimed at the gaps it identified — so the graph adapts to how well
the research is actually going.
"""

from langgraph.graph import END, StateGraph

from agent.confidence import should_continue
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
    # The adaptive edge: loop back for more research, or write the report.
    builder.add_conditional_edges(
        "reflect",
        should_continue,
        {"execute": "execute", "synthesize": "synthesize"},
    )
    builder.add_edge("synthesize", END)

    return builder.compile()


graph = build_graph()
