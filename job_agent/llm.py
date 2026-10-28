"""Bedrock access through Strands. Every LLM call in the backend goes through this module."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from config import settings
from utils import logger

M = TypeVar("M", bound=BaseModel)


class LLMNotConfigured(RuntimeError):
    pass


import re

# Claude 5-series models (Sonnet 5.5 rejected temperature with "temperature is deprecated for this model").
# For these, temperature is left out of the request; Strands drops None values.
_NO_TEMPERATURE = re.compile(r"claude-(sonnet|opus|haiku)-5")


def temperature_allowed(model_id: str) -> bool:
    return not _NO_TEMPERATURE.search(model_id or "")


def get_model(temperature: float = 0.2, max_tokens: int = 8000):
    if not settings.bedrock_configured:
        raise LLMNotConfigured("BEDROCK_MODEL_ID and AWS_REGION must be set in job_agent/.env")
    import boto3
    from strands.models import BedrockModel

    session = boto3.Session(profile_name=settings.AWS_PROFILE or None, region_name=settings.AWS_REGION)
    allowed = temperature_allowed(settings.BEDROCK_MODEL_ID)
    return BedrockModel(boto_session=session, model_id=settings.BEDROCK_MODEL_ID,
                        temperature=temperature if allowed else None, max_tokens=max_tokens)


FACTS_RULE = (
    "Use only facts present in the provided material. Never invent employers, titles, dates, metrics, "
    "technologies, certifications, or projects. If something is unknown, leave it empty."
)


def structured_with_tools(output_model: type[M], system_prompt: str, prompt: str, tools: list, *,
                          temperature: float = 0.2, max_tokens: int = 8000) -> M:
    """Like structured(), but the model may call read-only tools first (for example, to read a repo's code)."""
    from strands import Agent

    agent = Agent(model=get_model(temperature, max_tokens), tools=tools, system_prompt=system_prompt,
                  callback_handler=None)
    result = agent(prompt, structured_output_model=output_model)
    out = getattr(result, "structured_output", None)
    if out is None:
        raise RuntimeError("Model did not return structured output")
    logger.info("llm structured call with tools ok: %s", output_model.__name__)
    return out


def structured(output_model: type[M], system_prompt: str, prompt: str, *, temperature: float = 0.2,
               max_tokens: int = 8000) -> M:
    """One stateless Bedrock call that returns a validated pydantic object."""
    from strands import Agent

    agent = Agent(model=get_model(temperature, max_tokens), system_prompt=system_prompt, callback_handler=None)
    result = agent(prompt, structured_output_model=output_model)
    out = getattr(result, "structured_output", None)
    if out is None:
        raise RuntimeError("Model did not return structured output")
    logger.info("llm structured call ok: %s", output_model.__name__)
    return out
