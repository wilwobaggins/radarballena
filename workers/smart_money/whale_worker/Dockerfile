FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The runtime worker uses Python's standard library only.
COPY whale_worker.py ./whale_worker.py

# Verify Python 3.11 can import the runtime without starting its polling loop.
RUN python -c "import whale_worker"

CMD ["python", "-u", "whale_worker.py"]
