"""Create small, deterministic synthetic examples, not camera photographs.

No image-generation model or downloaded content is used. This demonstration
illustrates framing, alpha and basic extraction; it is not evidence that all
real photographs will segment correctly.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def make_photo(path):
    scale = 3
    size = 512
    yy, xx = np.mgrid[:size, :size].astype(np.float32)
    gradient = (xx - 256) * .012 + (yy - 256) * .007
    paper = np.stack((226 + gradient, 232 + gradient, 234 + gradient), axis=2)
    shape = Image.new("L", (size * scale, size * scale))
    draw = ImageDraw.Draw(shape)
    # An irregular ceramic pendant with a genuine opening near its top.
    points = [(249, 78), (290, 111), (329, 194), (361, 321), (341, 389),
              (286, 437), (216, 425), (168, 381), (151, 313), (181, 198), (209, 118)]
    draw.polygon([(x * scale, y * scale) for x, y in points], fill=255)
    draw.ellipse((226 * scale, 114 * scale, 265 * scale, 153 * scale), fill=0)
    shape = shape.resize((size, size), Image.Resampling.LANCZOS)
    coverage = np.array(shape, dtype=np.float32) / 255
    shifted = Image.new("L", (size, size))
    shifted.paste(shape, (7, 10))
    shadow = np.array(shifted.filter(ImageFilter.GaussianBlur(9)), dtype=np.float32) / 255
    paper *= (1 - .13 * shadow[..., None])
    texture = 2.2 * np.sin(xx * .63 + yy * .37) + 1.1 * np.sin(xx * 1.31 - yy * .89)
    light = (xx - 256) * .09 - (yy - 256) * .025 + texture
    ceramic = np.stack((166 + light, 83 + light * .65, 48 + light * .45), axis=2)
    color = Image.fromarray(np.clip(ceramic, 0, 255).astype(np.uint8))
    marks = ImageDraw.Draw(color)
    for offset in (-2, 0, 2):
        marks.line([(189, 255 + offset), (254, 325 + offset), (322, 254 + offset)],
                   fill=(107, 46, 27), width=3)
    marks.arc((204, 178, 307, 281), 5, 175, fill=(205, 119, 68), width=5)
    ceramic = np.array(color, dtype=np.float32)
    result = ceramic * coverage[..., None] + paper * (1 - coverage[..., None])
    Image.fromarray(np.clip(np.rint(result), 0, 255).astype(np.uint8)).save(path)


def make_artwork(path):
    scale = 3
    image = Image.new("RGBA", (320 * scale, 240 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((28 * scale, 43 * scale, 166 * scale, 181 * scale),
                 fill=(177, 77, 39, 255), outline=(224, 142, 70, 255), width=8 * scale)
    draw.ellipse((59 * scale, 74 * scale, 135 * scale, 150 * scale),
                 outline=(226, 164, 87, 255), width=5 * scale)
    star = [(243, 53), (258, 96), (301, 111), (258, 126),
            (243, 169), (228, 126), (185, 111), (228, 96)]
    draw.polygon([(x * scale, y * scale) for x, y in star], fill=(236, 182, 67, 255))
    image.resize((320, 240), Image.Resampling.LANCZOS).save(path)


def main():
    root = Path(__file__).resolve().parent
    (root / "photo").mkdir(exist_ok=True)
    (root / "artwork").mkdir(exist_ok=True)
    make_photo(root / "photo" / "synthetic_pendant.png")
    make_artwork(root / "artwork" / "synthetic_tokens.png")
    print("Created two synthetic examples. These are procedural illustrations, not photographs.")


if __name__ == "__main__":
    main()
