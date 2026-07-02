from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PAGES_DIR = ROOT / "qa_pages"
CONTACT_SHEET = ROOT / "qa_contact_sheet.png"
SUMMARY = ROOT / "qa_render_summary.md"


def main() -> None:
    pages = sorted(PAGES_DIR.glob("page-*.png"))
    thumb_w, thumb_h = 320, 180
    pad, label_h, cols = 18, 22, 4
    rows = (len(pages) + cols - 1) // cols
    sheet = Image.new(
        "RGB",
        (cols * (thumb_w + pad) + pad, rows * (thumb_h + label_h + pad) + pad),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    checks = []

    for idx, path in enumerate(pages):
        img = Image.open(path).convert("RGB")
        extrema = img.getextrema()
        is_flat = all(channel[0] == channel[1] for channel in extrema)
        checks.append({"file": path.name, "size": img.size, "flat": is_flat})

        thumb = img.copy()
        thumb.thumbnail((thumb_w, thumb_h))
        x = pad + (idx % cols) * (thumb_w + pad)
        y = pad + (idx // cols) * (thumb_h + label_h + pad)
        sheet.paste(thumb, (x + (thumb_w - thumb.width) // 2, y))
        draw.text(
            (x, y + thumb_h + 4),
            f"{idx + 1:02d} {path.name} {img.size[0]}x{img.size[1]}",
            fill=(20, 25, 35),
        )

    sheet.save(CONTACT_SHEET)
    sizes = sorted({item["size"] for item in checks})
    flat_pages = [item["file"] for item in checks if item["flat"]]
    SUMMARY.write_text(
        "\n".join(
            [
                "# Render Summary",
                "",
                f"- Rendered pages: {len(pages)}",
                f"- Unique page sizes: {sizes}",
                f"- Flat pages: {flat_pages}",
                f"- Contact sheet: `{CONTACT_SHEET.name}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"pages={len(pages)}")
    print(f"contact_sheet={CONTACT_SHEET}")
    print(f"flat_pages={flat_pages}")
    print(f"sizes={sizes}")


if __name__ == "__main__":
    main()
