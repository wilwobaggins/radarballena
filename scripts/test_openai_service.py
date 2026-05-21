import logging
from pydantic import BaseModel

from services.openai_service import OpenAIService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class TestOpenAIResponse(BaseModel):
    status: str
    resumen: str
    score: int


def main():
    service = OpenAIService()

    result = service.generate_structured_output(
        system_prompt=(
            "Eres un sistema de prueba. "
            "Devuelve solo una respuesta estructurada válida."
        ),
        user_prompt=(
            "Responde con status='ok', un resumen breve y score=100."
        ),
        schema=TestOpenAIResponse,
        max_output_tokens=500,
    )

    print("OpenAI respondió correctamente.")
    print(result.model_dump())


if __name__ == "__main__":
    main()