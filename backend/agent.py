"""ADK Agent definition for Formflow."""

from google.adk.agents import Agent

from backend.config import GEMINI_MODEL, SYSTEM_INSTRUCTION

formflow_agent = Agent(
    name="formflow_coach",
    model=GEMINI_MODEL,
    instruction=SYSTEM_INSTRUCTION,
)
