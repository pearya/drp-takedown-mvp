from __future__ import annotations

from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    print(f"DRP MVP worker placeholder is ready. Root: {root}")


if __name__ == "__main__":
    main()
