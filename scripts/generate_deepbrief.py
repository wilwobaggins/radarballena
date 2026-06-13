import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.logger_service import get_logger


logger = get_logger("generate_deepbrief")

LEGACY_WARNING = (
    "LEGACY_SCRIPT_WARNING: use python -m scripts.run_daily_pipeline for production DeepBriefs"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy wrapper for DeepBrief generation. "
            "Prefer python -m scripts.run_daily_pipeline."
        )
    )
    parser.add_argument(
        "--allow-legacy",
        action="store_true",
        help="Required acknowledgement to run this legacy wrapper.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logger.warning(LEGACY_WARNING)
    print(LEGACY_WARNING)

    if not args.allow_legacy:
        message = (
            "Legacy execution blocked. Re-run with --allow-legacy or use "
            "python -m scripts.run_daily_pipeline."
        )
        logger.error(message)
        print(message)
        return 2

    logger.warning(
        "Legacy wrapper enabled explicitly. Delegating to scripts.run_daily_pipeline."
    )

    from scripts import run_daily_pipeline

    run_daily_pipeline.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
