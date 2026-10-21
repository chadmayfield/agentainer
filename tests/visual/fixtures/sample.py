"""Generic sample used by the Agentainer visual review."""
from pathlib import Path

DEBUG = False
RETRIES = 3


def describe(path: Path) -> str:
    # Keep comments readable against the black background.
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return f"Ready: {path.name}, retries={RETRIES}"


if __name__ == "__main__":
    print(describe(Path("settings.yaml")))
