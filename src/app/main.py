"""
Entrypoint module so you can run:  python -m src.app.main
Later we will also add a setuptools entry point (jellyconv) to run as a CLI command.
"""

from app.cli import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli())
