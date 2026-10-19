"""Bounded, in-memory image processing without framework dependencies."""

import io
import time
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from .commands import Operation


class ImageProcessingError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    max_pixels: int = 16_000_000
    max_frames: int = 200
    max_total_pixels: int = 24_000_000
    max_output_bytes: int = 20 * 1024 * 1024
    timeout: float = 30


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    format: str
    note: str = ""


class LimitedBuffer(io.BytesIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise ImageProcessingError("处理结果过大，请使用尺寸更小的图片。")
        return super().write(data)


def _transform(frame: Image.Image, operation: Operation) -> Image.Image:
    name = operation.name
    w, h = frame.size
    if name in {"左对称", "右对称", "上对称", "下对称"}:
        result = frame.copy()
        # Preserve the central row/column when an image has an odd dimension.
        if name == "左对称":
            half = frame.crop((0, 0, w // 2, h))
            result.paste(ImageOps.mirror(half), (w - w // 2, 0))
        elif name == "右对称":
            half = frame.crop((w - w // 2, 0, w, h))
            result.paste(ImageOps.mirror(half), (0, 0))
        elif name == "上对称":
            half = frame.crop((0, 0, w, h // 2))
            result.paste(ImageOps.flip(half), (0, h - h // 2))
        else:
            half = frame.crop((0, h - h // 2, w, h))
            result.paste(ImageOps.flip(half), (0, 0))
        return result
    if name == "左右翻转":
        return ImageOps.mirror(frame)
    if name == "上下翻转":
        return ImageOps.flip(frame)
    if name == "顺时针":
        return frame.transpose(Image.Transpose.ROTATE_270)
    if name == "逆时针":
        return frame.transpose(Image.Transpose.ROTATE_90)
    if name == "旋转":
        return frame.rotate(
            -operation.value, resample=Image.Resampling.BICUBIC, expand=True
        )
    if name in {"反色", "灰度"}:
        rgb = frame.convert("RGB")
        result = (
            ImageOps.invert(rgb)
            if name == "反色"
            else ImageOps.grayscale(rgb).convert("RGB")
        ).convert("RGBA")
        result.putalpha(frame.getchannel("A"))
        return result
    if name in {"倒放", "调速", "原图"}:
        return frame.copy()
    raise ImageProcessingError("不支持的图片操作。")


def _gif_palette(frame: Image.Image) -> Image.Image:
    # Reserve a single transparent index across all full-canvas frames.
    result = frame.convert("RGB").quantize(colors=255)
    palette = result.getpalette() or []
    result.putpalette((palette + [0] * 768)[:768])
    result.paste(255, mask=frame.getchannel("A").point(lambda a: 255 if a < 128 else 0))
    result.info.clear()
    result.info["transparency"] = 255
    return result


def process_image(
    data: bytes, operation: Operation, limits: Limits = Limits()
) -> ProcessedImage:
    deadline = time.monotonic() + limits.timeout

    def check_time():
        if time.monotonic() > deadline:
            raise ImageProcessingError("图片处理超时，请减少图片尺寸或 GIF 帧数。")

    def check_pixels(size, total=0):
        pixels = size[0] * size[1]
        if pixels > limits.max_pixels or total + pixels > limits.max_total_pixels:
            raise ImageProcessingError("图片像素或 GIF 总像素超限，请缩小图片。")
        return total + pixels

    try:
        with Image.open(io.BytesIO(data)) as image:
            check_pixels(image.size)
            is_gif = image.format == "GIF"
            if operation.name in {"倒放", "调速"} and not is_gif:
                raise ImageProcessingError("倒放和调速仅支持 GIF 图片。")
            if not is_gif:
                if getattr(image, "is_animated", False):
                    raise ImageProcessingError("此动画格式暂不支持，请先转换为 GIF。")
                frame = ImageOps.exif_transpose(image).convert("RGBA")
                result = _transform(frame, operation)
                check_pixels(result.size)
                check_time()
                with LimitedBuffer(limits.max_output_bytes) as output:
                    result.save(output, format="PNG")
                    check_time()
                    return ProcessedImage(output.getvalue(), "PNG")

            frames, durations = [], []
            loop = image.info.get("loop")
            total_pixels = 0
            for index in range(limits.max_frames + 1):
                check_time()
                try:
                    image.seek(index)
                except EOFError:
                    break
                if index == limits.max_frames:
                    raise ImageProcessingError(f"GIF 超过 {limits.max_frames} 帧限制。")
                total_pixels = check_pixels(image.size, total_pixels)
                # Pillow already composites GIF local frames and applies disposal.
                frame = _transform(image.convert("RGBA"), operation)
                check_pixels(frame.size)
                frames.append(_gif_palette(frame))
                durations.append(max(10, int(image.info.get("duration", 100)) or 100))
            if not frames:
                raise ImageProcessingError("GIF 中没有有效帧。")
            if operation.name == "倒放":
                frames.reverse()
                durations.reverse()
            note = ""
            if operation.name == "调速":
                requested = [duration / operation.value for duration in durations]
                durations = [
                    max(20, round(duration / 10) * 10) for duration in requested
                ]
                if any(duration < 20 for duration in requested):
                    note = "部分帧已限制为最短 20ms，实际加速倍率可能低于设定值。"
            if any(duration > 655350 for duration in durations):
                raise ImageProcessingError("GIF 单帧时长过长，请提高调速倍率。")
            options = {"loop": loop} if loop is not None else {}
            check_time()
            with LimitedBuffer(limits.max_output_bytes) as output:
                frames[0].save(
                    output,
                    format="GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    disposal=2,
                    background=255,
                    transparency=255,
                    optimize=False,
                    **options,
                )
                check_time()
                return ProcessedImage(output.getvalue(), "GIF", note)
    except ImageProcessingError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageProcessingError("图片尺寸过大，请缩小后重试。") from exc
    except (UnidentifiedImageError, OSError, ValueError, EOFError) as exc:
        raise ImageProcessingError("图片无法解码，可能已损坏或格式不受支持。") from exc
