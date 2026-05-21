import os
import logging
from typing import Type, TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel


load_dotenv()

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAIService:
    def __init__(self, model: str | None = None):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en .env")

        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=api_key)

    def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        max_output_tokens: int = 1500,
    ) -> T:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=schema,
            max_output_tokens=max_output_tokens,
        )

        usage = getattr(response, "usage", None)

        if usage:
            logger.info("OpenAI usage: %s", usage)
        else:
            logger.info("OpenAI response completed without usage metadata.")

        return response.output_parsed