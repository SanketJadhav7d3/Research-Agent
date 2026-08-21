"""Run the agent from the command line.

    uv run python -m agent.run "What are the risks of X?"

Sprint 4 puts this behind an HTTP endpoint; until then this is how the graph is
exercised.
"""

import logging
import sys

# Windows consoles default to cp1252, which cannot encode much of what appears
# in real sources (accented author names, dashes, symbols). Reports are UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import MAX_ITERATIONS_CAP
from agent.graph import graph


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="  %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print('Usage: python -m agent.run "your research goal"', file=sys.stderr)
        return 2

    goal = " ".join(sys.argv[1:])
    print(f"\nGoal: {goal}\n" + "-" * 60)

    final = graph.invoke({
        "goal": goal,
        "iteration": 0,
        "max_iterations": MAX_ITERATIONS_CAP,
        "tool_calls": [],
        "findings": [],
    })

    print("-" * 60)
    print(f"\nClarified:  {final['clarified_goal']}")
    print(f"Plan:       {len(final['plan'])} sub-questions")
    for q in final["plan"]:
        print(f"  - {q}")
    print(f"Tool calls: {len(final['tool_calls'])}")
    print(f"Confidence: {final['confidence']:.2f} - {final['confidence_reason']}")
    print(f"\n{'=' * 60}\n{final['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
