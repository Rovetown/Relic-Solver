from __future__ import annotations

import sys
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

SOURCE_DIR = Path("assets/font-sources")
TARGET_DIR = Path("src/webapp/static/fonts")

KEEP = sorted(
    set(range(0x20, 0x7F)) | {0x00A0, 0x2013, 0x2014, 0x2026},
)


def subset_one(src: Path, dst: Path) -> tuple[int, int]:
    font = TTFont(src)
    options = Options()
    options.flavor = "woff2"
    options.retain_gids = False
    options.desubroutinize = False
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True

    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=KEEP)
    subsetter.subset(font)
    font.flavor = "woff2"
    font.save(dst)
    font.close()
    return src.stat().st_size, dst.stat().st_size


def main() -> int:
    if not SOURCE_DIR.is_dir():
        print(f"missing {SOURCE_DIR}", file=sys.stderr)
        return 1

    before = after = 0
    for src in sorted(SOURCE_DIR.glob("*.woff2")):
        dst = TARGET_DIR / src.name
        was, now = subset_one(src, dst)
        before += was
        after += now
        print(f"{src.name}: {was:,} B -> {now:,} B  ({100 - now * 100 // was}% smaller)")

    print(f"total: {before:,} B -> {after:,} B  (saved {before - after:,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
