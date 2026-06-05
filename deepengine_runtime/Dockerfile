FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services ./services
COPY scripts ./scripts
COPY prompts ./prompts
COPY schemas ./schemas
COPY deepengine_worker.py .

CMD ["python", "deepengine_worker.py"]