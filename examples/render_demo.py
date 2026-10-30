"""Render the synthetic example comparison using an installed Cutout Prep."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw


def tile(image, size=(440, 440)):
    image = image.convert("RGBA")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    background = Image.new("RGB", size, (66, 70, 74))
    background.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2), image)
    return background


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root.parent / "docs/images/synthetic-demo.jpg")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (920, 1030), (43, 45, 48))
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 12), "SYNTHETIC EXAMPLES - procedural illustrations, not real-photo validation", fill="white")
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
    # Place temporary review files beside the explicitly selected output.
    with tempfile.TemporaryDirectory(prefix=".cutout-demo-", dir=output.parent) as temporary:
        for row, (folder, filename, preset) in enumerate((
            ("photo", "synthetic_pendant", "photo"),
            ("artwork", "synthetic_tokens", "artwork"),
        )):
            destination = Path(temporary) / folder
            result = subprocess.run(
                [sys.executable, "-B", "-m", "cutout_prep", str(root / folder),
                 "--output", str(destination), "--preset", preset, "--size", "512", "--padding", "24"],
                env=env, capture_output=True, text=True,
            )
            if result.returncode not in (0, 2):
                raise RuntimeError(result.stdout + result.stderr)
            prepared = destination / (filename + "_BaseColor.png")
            if not prepared.is_file():
                raise RuntimeError("Synthetic example failed to export: " + result.stdout + result.stderr)
            y = 70 + row * 480
            with Image.open(root / folder / (filename + ".png")) as before:
                sheet.paste(tile(before), (15, y))
            with Image.open(prepared) as after:
                sheet.paste(tile(after), (465, y))
            draw.text((18, y - 21), preset + " input", fill="white")
            draw.text((468, y - 21), preset + " prepared / transparent", fill="white")
    sheet.save(output, quality=95)
    print("Wrote synthetic comparison: " + str(output))


if __name__ == "__main__":
    main()
