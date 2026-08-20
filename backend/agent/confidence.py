"""Confidence gating — the decision that makes the graph adaptive.

After Reflect scores its own work, this decides whether the agent writes the
report or goes back for another round of research aimed at the gaps it just
identified.
"""

import logging

from agent.events import emit
from agent.state import AgentState

CONFIDENCE_THRESHOLD = 0.75

log = logging.getLogger(__name__)


def should_continue(state: AgentState) -> str:
    """Return the name of the next node: "execute" or "synthesize"."""
    confidence = state.get("confidence", 0.0)
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if confidence >= CONFIDENCE_THRESHOLD:
        emit("gate", decision="synthesize", reason="confident",
             score=confidence, threshold=CONFIDENCE_THRESHOLD, loop=iteration)
        log.info("confidence %.2f >= %.2f - writing report",
                 confidence, CONFIDENCE_THRESHOLD)
        return "synthesize"

    if iteration >= max_iterations:
        # Exit unconfident rather than loop forever. Synthesize is told to state
        # the limitations plainly.
        emit("gate", decision="synthesize", reason="max_iterations",
             score=confidence, threshold=CONFIDENCE_THRESHOLD, loop=iteration)
        log.warning("confidence %.2f but hit %d iterations - writing report anyway",
                    confidence, max_iterations)
        return "synthesize"

    emit("gate", decision="execute", reason="low_confidence",
         score=confidence, threshold=CONFIDENCE_THRESHOLD, loop=iteration,
         gaps=state.get("gaps", []))
    log.info("confidence %.2f < %.2f - researching again (loop %d)",
             confidence, CONFIDENCE_THRESHOLD, iteration + 1)
    return "execute"
