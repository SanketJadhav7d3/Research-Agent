"""Schemas constraining what the LLM may return.

Each is passed to `.with_structured_output()`, so the model returns a validated
object rather than prose we would have to parse. Field descriptions are part of
the prompt the model sees — they are instructions, not just documentation.
"""

from pydantic import BaseModel, Field


class ClarifiedGoal(BaseModel):
    clarified_goal: str = Field(
        description="The research goal restated precisely, with scope and timeframe made explicit."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Ambiguities in the original goal that you resolved, and how you resolved them.",
    )


class ResearchPlan(BaseModel):
    sub_questions: list[str] = Field(
        description="Three to five concrete sub-questions that together answer the goal. "
        "Each must be independently researchable."
    )


class Reflection(BaseModel):
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How well the findings answer the goal. 0.0 = no useful evidence, "
        "1.0 = fully answered with strong sources.",
    )
    reason: str = Field(
        description="One or two sentences justifying the score, naming what is missing."
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Sub-questions that remain weakly answered.",
    )


class ImprovedPrompt(BaseModel):
    improved: str = Field(
        description="The research question rewritten to be clearer and more specific. "
        "Keep the user's actual subject and intent — do not add constraints, "
        "dates, regions or entities they did not mention."
    )
    changes: list[str] = Field(
        default_factory=list,
        description="Short notes on what you changed and why, one per change. "
        "Empty if the question was already well specified.",
    )
