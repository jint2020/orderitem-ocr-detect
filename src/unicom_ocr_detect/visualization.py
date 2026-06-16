"""OCR 结果可视化输出。

当前阶段可视化图用于人工快速检查：

- OCR 是否框到了页面文字。
- 字段抽取框是否落在正确 value 上。
- 哪些字段为空或没有 box，需要回看 JSON 中的 `source` 和 `raw_ocr`。

蓝色框表示所有 OCR 文本框，红色框表示已抽取字段的 value 框。
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from unicom_ocr_detect.fields import FieldResult
from unicom_ocr_detect.ocr_result import OcrItem


def save_label_image(
    image_path: Path,
    ocr_items: list[OcrItem],
    fields: dict[str, FieldResult],
    output_path: Path,
    rotation_degrees: int = 0,
) -> None:
    """在原图上绘制 OCR 框和字段框，并保存到 `output_path`。

    Args:
        image_path: 原始图片路径。
        ocr_items: 归一化后的 OCR 文本项。
        fields: 字段抽取结果。
        output_path: 标注图输出路径。
        rotation_degrees: OCR 实际使用的候选角度。非 0 时，先把原图旋转到
            同一方向再绘制框，确保框坐标和图片对齐。
    """
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
    """绘制矩形框。

    Pillow 的 rectangle 支持 width 参数；坐标转 int 是为了避免浮点坐标
    在不同 Pillow 版本里表现不一致。
    """
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    draw.rectangle((x1, y1, x2, y2), outline=color, width=width)


def _draw_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[float, float, float, float],
    font: ImageFont.ImageFont,
) -> None:
    """在字段框左上角绘制字段名。

    当前只做轻量标注，不追求复杂避让。字段框是给人工检查用，JSON 才是
    机器消费的权威输出。
    """
    x1, y1, _, _ = [int(round(value)) for value in box]
    label_origin = (x1, max(0, y1 - 18))
    text_box = draw.textbbox(label_origin, text, font=font)
    draw.rectangle(text_box, fill=(255, 64, 64))
    draw.text(label_origin, text, fill=(255, 255, 255), font=font)


def _load_font() -> ImageFont.ImageFont:
    """加载默认字体。

    macOS/Linux 环境字体路径差异较大。第一阶段只需要可视化框，文字标签
    如果中文字体不可用，使用 Pillow 默认字体即可。
    """
    return ImageFont.load_default()
