"""Render celebration and condolence posters entirely in memory."""

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .image_ops import ImageProcessingError, LimitedBuffer, Limits, ProcessedImage

FONT_PATH = Path(__file__).resolve().parents[1] / "resources" / "NotoSansSC-Bold.otf"
BACKGROUND_ROOT = Path(__file__).resolve().parents[1] / "resources" / "reports"


def generate_report(
    kind: str, text: str, font_size: int = 65, limits: Limits = Limits()
) -> ProcessedImage:
    """Create a poster with wrapped text and a fitted font size.

    Args:
        kind: Either the celebration or condolence command name.
        text: User content, including optional explicit line breaks.
        font_size: Preferred body size in pixels, reduced when necessary.
        limits: Shared output size, pixel and processing time limits.

    Returns:
        A PNG image ready to send through AstrBot.

    Raises:
        ImageProcessingError: Content, resources or rendering exceed the limits.
    """
    deadline = time.monotonic() + limits.timeout
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").strip()
    if kind not in {"喜报", "悲报"}:
        raise ImageProcessingError("不支持的喜报、悲报类型。")
    if not text:
        raise ImageProcessingError(f"用法：{kind} 你的内容")
    if len(text) > 500:
        raise ImageProcessingError("喜报、悲报内容最多 500 字，请缩短后重试。")
    if any(ord(character) < 32 and character != "\n" for character in text):
        raise ImageProcessingError("内容包含不支持的控制字符，请删除后重试。")
    happy = kind == "喜报"
    background_path = BACKGROUND_ROOT / ("congrats.jpg" if happy else "uncongrats.jpg")
    try:
        with Image.open(background_path) as background:
            width, height = background.size
            if width * height > min(limits.max_pixels, limits.max_total_pixels):
                raise ImageProcessingError(
                    "喜报、悲报画布超过像素限制，请调高像素上限。"
                )
            image = background.convert("RGB")
    except OSError as exc:
        raise ImageProcessingError(
            "喜报、悲报背景无法读取，请重新安装插件以恢复 resources/reports 素材。"
        ) from exc
    foreground = (255, 0, 0) if happy else (0, 0, 0)
    outline = (255, 255, 0) if happy else (255, 255, 255)
    draw = ImageDraw.Draw(image)
    # Keep the template's existing title and flowers outside the body area.
    left, top, right, bottom = (
        int(width * 0.1),
        int(height * 0.24),
        int(width * 0.9),
        int(height * 0.82),
    )
    try:
        # Fit against actual glyph advances, preserving explicit paragraph breaks.
        for size in range(max(24, min(160, font_size)), 19, -1):
            if time.monotonic() > deadline:
                raise ImageProcessingError("喜报、悲报生成超时，请缩短内容后重试。")
            font = ImageFont.truetype(str(FONT_PATH), size)
            lines = []
            for paragraph in text.split("\n"):
                line = ""
                for character in paragraph:
                    if (
                        line
                        and draw.textlength(line + character, font=font)
                        > right - left - 6
                    ):
                        lines.append(line)
                        line = character
                    else:
                        line += character
                lines.append(line)
            wrapped = "\n".join(lines)
            spacing = max(8, size // 4)
            bbox = draw.multiline_textbbox(
                (0, 0),
                wrapped,
                font=font,
                spacing=spacing,
                stroke_width=3,
                align="center",
            )
            if bbox[2] - bbox[0] <= right - left and bbox[3] - bbox[1] <= bottom - top:
                break
        else:
            raise ImageProcessingError("文字或换行过多，无法放入画布，请缩短后重试。")
        position = (
            (left + right - bbox[0] - bbox[2]) / 2,
            (top + bottom - bbox[1] - bbox[3]) / 2,
        )
        draw.multiline_text(
            position,
            wrapped,
            font=font,
            fill=foreground,
            spacing=spacing,
            align="center",
            stroke_width=3,
            stroke_fill=outline,
        )
        if time.monotonic() > deadline:
            raise ImageProcessingError("喜报、悲报生成超时，请缩短内容后重试。")
        with LimitedBuffer(limits.max_output_bytes) as output:
            image.save(output, format="PNG")
            return ProcessedImage(output.getvalue(), "PNG")
    except OSError as exc:
        raise ImageProcessingError(
            "喜报、悲报中文字体无法读取，请重新安装插件以恢复 resources 字体文件。"
        ) from exc
