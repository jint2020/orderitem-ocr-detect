from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.models.ocr_models import FieldResult, OcrItem


def save_label_image(
    image_path: Path,
    ocr_items: list[OcrItem],
    fields: dict[str, FieldResult],
    output_path: Path,
    rotation_degrees: int = 0,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB").rotate(rotation_degrees % 360, expand=True)

    draw = ImageDraw.Draw(image)
    font = _load_font()

    for item in ocr_items:
        _draw_box(draw, item.box, color=(0, 102, 255), width=2)

    for field_name, field in fields.items():
        if field.box is None:
            continue
        _draw_box(draw, field.box, color=(255, 64, 64), width=4)
        _draw_label(draw, field_name, field.box, font)

    image.save(output_path)


def _draw_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    color: tuple[int, int, int],
    width: int,
) -> None:
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    draw.rectangle((x1, y1, x2, y2), outline=color, width=width)


def _draw_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[float, float, float, float],
    font: ImageFont.ImageFont,
) -> None:
    x1, y1, _, _ = [int(round(value)) for value in box]
    label_origin = (x1, max(0, y1 - 18))
    text_box = draw.textbbox(label_origin, text, font=font)
    draw.rectangle(text_box, fill=(255, 64, 64))
    draw.text(label_origin, text, fill=(255, 255, 255), font=font)


def _load_font() -> ImageFont.ImageFont:
    return ImageFont.load_default()
