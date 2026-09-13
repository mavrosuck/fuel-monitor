"""Compatibility entry point for the one-off dry-run diagnostic."""

import os


def main() -> None:
    os.environ["DRY_RUN"] = "1"
    from app.runner import main as run

    run()


if __name__ == "__main__":
    main()
