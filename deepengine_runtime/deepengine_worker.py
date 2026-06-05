import os
import time
import subprocess
from datetime import datetime, timezone

INTERVAL_SECONDS = int(os.getenv("DEEPENGINE_INTERVAL_SECONDS", "300"))
COMMAND = os.getenv(
    "DEEPENGINE_COMMAND",
    "python -m scripts.run_daily_pipeline"
)

def log(message: str):
    now = datetime.now(timezone.utc).isoformat()
    print(f"[deepengine-worker] {now} {message}", flush=True)

def run_once():
    log(f"Starting command: {COMMAND}")

    result = subprocess.run(
        COMMAND,
        shell=True,
        text=True,
        capture_output=False,
    )

    if result.returncode == 0:
        log("Pipeline finished OK")
    else:
        log(f"Pipeline failed with exit code {result.returncode}")

def main():
    log("Worker started")

    while True:
        try:
            run_once()
        except Exception as error:
            log(f"Unhandled error: {error}")

        log(f"Sleeping {INTERVAL_SECONDS}s")
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()