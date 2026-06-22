import os
import time
import subprocess
from datetime import datetime, timezone

INTERVAL_SECONDS = int(os.getenv("DEEPENGINE_INTERVAL_SECONDS", "300"))
COMMAND = os.getenv(
    "DEEPENGINE_COMMAND",
    "python -m scripts.run_daily_pipeline"
)
CLOSING_RECHECK_ENABLED = os.getenv("CLOSING_RECHECK_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CLOSING_RECHECK_INTERVAL_SECONDS = int(
    os.getenv("CLOSING_RECHECK_INTERVAL_SECONDS", "3600")
)
CLOSING_RECHECK_COMMAND = os.getenv(
    "CLOSING_RECHECK_COMMAND",
    "python -m scripts.run_closing_rechecks --once",
)

def log(message: str):
    now = datetime.now(timezone.utc).isoformat()
    print(f"[deepengine-worker] {now} {message}", flush=True)

def run_command(command: str, label: str):
    log(f"Starting {label}: {command}")

    result = subprocess.run(
        command,
        shell=True,
        text=True,
        capture_output=False,
    )

    if result.returncode == 0:
        log(f"{label} finished OK")
    else:
        log(f"{label} failed with exit code {result.returncode}")

def main():
    log("Worker started")

    last_pipeline_run_at = 0.0
    last_closing_recheck_run_at = 0.0

    while True:
        try:
            now = time.monotonic()
            ran_anything = False

            if now - last_pipeline_run_at >= INTERVAL_SECONDS:
                run_command(COMMAND, "pipeline")
                last_pipeline_run_at = time.monotonic()
                ran_anything = True

            if CLOSING_RECHECK_ENABLED and (
                now - last_closing_recheck_run_at >= CLOSING_RECHECK_INTERVAL_SECONDS
            ):
                run_command(CLOSING_RECHECK_COMMAND, "closing_recheck")
                last_closing_recheck_run_at = time.monotonic()
                ran_anything = True
        except Exception as error:
            log(f"Unhandled error: {error}")
            ran_anything = True

        now = time.monotonic()
        next_pipeline_in = max(0.0, INTERVAL_SECONDS - (now - last_pipeline_run_at))
        sleep_seconds = next_pipeline_in

        if CLOSING_RECHECK_ENABLED:
            next_recheck_in = max(
                0.0,
                CLOSING_RECHECK_INTERVAL_SECONDS - (
                    now - last_closing_recheck_run_at
                ),
            )
            sleep_seconds = min(sleep_seconds, next_recheck_in)

        if ran_anything and sleep_seconds <= 0:
            sleep_seconds = 1

        sleep_seconds = max(1.0, min(sleep_seconds, 60.0))
        log(f"Sleeping {sleep_seconds}s")
        time.sleep(sleep_seconds)

if __name__ == "__main__":
    main()
