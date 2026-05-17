from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "config" / "ocr_evaluation_profiles" / "fixtures" / "synthetic_medical_directml.png"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def main() -> int:
    width, height = 900, 620
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = _font(34)
    body_font = _font(28)
    table_font = _font(26)
    small_font = _font(20)

    black = (20, 20, 20)
    grid = (45, 45, 45)

    draw.text((120, 72), "EYEX SYNTHETIC OCR EVAL", fill=black, font=title_font)
    draw.text((120, 140), "Document type: deidentified inpatient note", fill=black, font=body_font)
    draw.text((120, 182), "Patient code: SYN-0001  Age: 66  Sex: M", fill=black, font=body_font)
    draw.text((120, 240), "Assessment: no hypertension or diabetes documented.", fill=black, font=body_font)

    left, top = 120, 313
    columns = [left, 280, 430, 590, 740]
    rows = [top, 353, 393, 433]
    for x in columns:
        draw.line((x, rows[0], x, rows[-1]), fill=grid, width=2)
    for y in rows:
        draw.line((columns[0], y, columns[-1], y), fill=grid, width=2)

    table_rows = [
        ["Test", "Result", "Unit", "Flag"],
        ["WBC", "8.6", "10^9/L", "normal"],
        ["CRP", "3.2", "mg/L", "normal"],
    ]
    for row_index, row in enumerate(table_rows):
        y = rows[row_index] + 7
        for col_index, text in enumerate(row):
            draw.text((columns[col_index] + 12, y), text, fill=black, font=table_font)

    draw.text((120, 490), "Synthetic only. Contains no PHI and no real patient data.", fill=black, font=small_font)

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(FIXTURE_PATH, format="PNG", optimize=True)
    print(FIXTURE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
