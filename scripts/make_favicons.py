from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

IMAGES = Path("src/webapp/static/images")
SOURCE = IMAGES / "favicon-96x96.png"
BLOCK = 6
ICO = Path("src/webapp/static/favicon.ico")


def native_grid(path: Path, block: int) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    width, height = image.size
    if width % block or height % block:
        raise ValueError(f"{path} is {width}x{height}, not divisible by {block}")
    return image.resize((width // block, height // block), Image.NEAREST)


def write_ico(images: list[Image.Image], target: Path) -> None:
    blobs = []
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        blobs.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries = b""
    for image, blob in zip(images, blobs, strict=True):
        width, height = image.size
        entries += struct.pack(
            "<BBBBHHII",
            0 if width >= 256 else width,
            0 if height >= 256 else height,
            0,
            0,
            1,
            32,
            len(blob),
            offset,
        )
        offset += len(blob)

    target.write_bytes(header + entries + b"".join(blobs))


def main() -> int:
    native = native_grid(SOURCE, BLOCK)
    doubled = native.resize((native.width * 2, native.height * 2), Image.NEAREST)

    for image, name in ((native, "favicon-16x16.png"), (doubled, "favicon-32x32.png")):
        path = IMAGES / name
        image.save(path, format="PNG", optimize=True)
        print(f"{name}: {image.width}x{image.height}, {path.stat().st_size:,} B")

    write_ico([native, doubled], ICO)
    print(f"favicon.ico: 16x16 + 32x32, {ICO.stat().st_size:,} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
