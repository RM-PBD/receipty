"""Build a multi-resolution macOS icon from Receipty's source artwork."""

import sys
from pathlib import Path

from PIL import Image


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: build_icon.py SOURCE.png OUTPUT.icns")

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    with Image.open(source) as image:
        icon = image.convert("RGBA")
        if icon.size != (1024, 1024):
            icon = icon.resize((1024, 1024), Image.Resampling.LANCZOS)
        icon.save(destination, format="ICNS")


if __name__ == "__main__":
    main()
