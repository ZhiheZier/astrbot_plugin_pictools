"""Adapted meme animation layouts from Lucy's pic_toolbox (AGPL-3.0).

Source revision: 4e9843e06b907c08d91fc48dd1c855668223f4d7.
See resources/memes/README.md for sources, licensing and porting changes.
"""

import io
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, UnidentifiedImageError

from .image_ops import (
    ImageProcessingError,
    LimitedBuffer,
    Limits,
    ProcessedImage,
    _gif_palette,
)

ASSET_ROOT = Path(__file__).resolve().parents[1] / "resources" / "memes"
MEME_SPECS = {
    "摸头": ("petpet_hand.png", 5, (112, 112), 60),
    "发射": ("shoot_frames", 13, (160, 97), 150),
    "杀": ("behead_frames", 21, (284, 284), 50),
    "操你": ("do_frames", 3, (300, 300), 50),
    "抽你": ("lash_frames", 9, (120, 120), 50),
}
_BEHEAD_LOCS = [
    (80, 72, 0),
    (83, 73, 0),
    (82, 73, 0),
    (78, 73, 0),
    (72, 74, 0),
    (72, 75, 0),
    (73, 76, 0),
    (73, 76, 0),
    (73, 76, 0),
    (74, 76, 0),
    (74, 76, 0),
    (70, 73, -12),
    (61, 62, -25),
    (49, 40, -45),
    (46, 30, -65),
    (50, 35, -85),
    (39, 34, -105),
    (19, 45, -135),
    (9, 91, -155),
    (6, 161, -175),
    (-4, 248, -180),
]
_LASH_SELF = [
    (84, 25),
    (87, 23),
    (87, 27),
    (86, 28),
    (62, 26),
    (59, 28),
    (76, 20),
    (85, 24),
    (80, 23),
]
_LASH_TARGET = [
    (12, 69),
    (15, 66),
    (14, 67),
    (15, 66),
    (17, 67),
    (14, 63),
    (21, 56),
    (15, 62),
    (17, 69),
]


def _circle_avatar(image: Image.Image, size: int, angle: float = 0) -> Image.Image:
    """Fit an avatar to a circle while preserving its original alpha channel.

    Args:
        image: An RGBA input image.
        size: Diameter of the result in pixels.
        angle: Counterclockwise rotation applied within the fixed result size.

    Returns:
        A circular RGBA avatar with transparent corners.
    """
    image = ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size))
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    if angle:
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC)
    return image


def _face_center(image: Image.Image) -> tuple[tuple[float, float] | None, str]:
    """Locate the largest anime, frontal or profile face for shooting crops.

    Args:
        image: RGBA image to inspect; detection is bounded to a 640-pixel side.

    Returns:
        A normalized face center and an optional fallback explanation.
    """
    try:
        import cv2
        import numpy as np

        sample = image.convert("L")
        sample.thumbnail((640, 640))
        gray = np.asarray(sample)
        cascade_paths = [
            ASSET_ROOT / "lbpcascade_animeface.xml",
            Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml",
            Path(cv2.data.haarcascades) / "haarcascade_profileface.xml",
        ]
        for path in cascade_paths:
            cascade = cv2.CascadeClassifier(str(path))
            if cascade.empty():
                continue
            for scale, neighbors in [(1.05, 4), (1.03, 3), (1.01, 2)]:
                faces = cascade.detectMultiScale(
                    cv2.equalizeHist(gray),
                    scaleFactor=scale,
                    minNeighbors=neighbors,
                    minSize=(20, 20),
                )
                if len(faces):
                    x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
                    return (
                        (x + width / 2) / sample.width,
                        (y + height / 2) / sample.height,
                    ), ""
    except (ImportError, OSError):
        return None, "未启用人脸定位，已按图片中心裁剪。"
    except Exception:
        return None, "人脸定位未成功，已按图片中心裁剪。"
    return None, "未检测到人脸，已按图片中心裁剪。"


def generate_meme(
    kind: str,
    target_data: bytes,
    commander_data: bytes | None = None,
    limits: Limits = Limits(),
) -> ProcessedImage:
    """Render one of the five upstream meme layouts with bounded input/output.

    Args:
        kind: Canonical meme command name.
        target_data: Target image or avatar bytes; animations use their first frame.
        commander_data: Sender avatar bytes, required for the two-avatar layouts.
        limits: Shared pixel, frame count, output size and time limits.

    Returns:
        A looping GIF and any first-frame or face-crop explanation.

    Raises:
        ImageProcessingError: Input, template resources or output are invalid.
    """
    deadline = time.monotonic() + limits.timeout
    if kind not in MEME_SPECS:
        raise ImageProcessingError("不支持的表情包类型。")
    asset, count, size, duration = MEME_SPECS[kind]
    pixels = size[0] * size[1]
    if count > limits.max_frames:
        raise ImageProcessingError("表情包帧数超过当前限制，请调高 GIF 最大帧数。")
    if pixels > limits.max_pixels or count * pixels > limits.max_total_pixels:
        raise ImageProcessingError("表情包画布超过当前像素限制。")
    if kind in {"操你", "抽你"} and commander_data is None:
        raise ImageProcessingError("双人表情包需要发送者和目标的两张头像。")
    try:
        inputs = [target_data]
        if kind in {"操你", "抽你"}:
            inputs.append(commander_data)
        avatars, notes = [], []
        for data in inputs:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > limits.max_pixels:
                    raise ImageProcessingError("输入图片像素超限，请缩小后重试。")
                if getattr(image, "is_animated", False):
                    notes.append("表情包使用输入图片的首帧生成。")
                avatars.append(ImageOps.exif_transpose(image).convert("RGBA"))
        target = avatars[0]
        commander = avatars[1] if len(avatars) == 2 else None
        if kind == "摸头":
            target = _circle_avatar(target, 112)
            with Image.open(ASSET_ROOT / asset) as source:
                if source.size != (560, 112):
                    raise ImageProcessingError("摸头素材尺寸异常，请重新安装插件。")
                hand = source.convert("RGBA")
        elif kind == "发射":
            focal, note = _face_center(target)
            if note:
                notes.append(note)
            if focal is None:
                focal = (0.5, 0.5)
            # Crop before resizing to avoid huge intermediates for narrow inputs.
            crop_width = min(target.width, target.height * size[0] / size[1])
            crop_height = crop_width * size[1] / size[0]
            left = max(
                0,
                min(
                    target.width - crop_width, focal[0] * target.width - crop_width / 2
                ),
            )
            top = max(
                0,
                min(
                    target.height - crop_height,
                    focal[1] * target.height - crop_height / 2,
                ),
            )
            target = target.resize(
                size,
                Image.Resampling.LANCZOS,
                box=(left, top, left + crop_width, top + crop_height),
            )
        elif kind == "杀":
            target = ImageOps.fit(target, (75, 75), Image.Resampling.LANCZOS)
        elif kind == "操你":
            target = _circle_avatar(target, 112, 90)
            commander = _circle_avatar(commander, 122, -15)
        else:
            target = _circle_avatar(target, 22, 30)
            commander = _circle_avatar(commander, 22)

        frames = []
        offsets = [
            (0, 0, 0, 0),
            (-4, 12, 4, -12),
            (-12, 18, 12, -18),
            (-8, 12, 4, -12),
            (-4, 0, 0, 0),
        ]
        for index in range(count):
            if time.monotonic() > deadline:
                raise ImageProcessingError("表情包生成超时，请缩小输入图片后重试。")
            if kind == "摸头":
                canvas = Image.new("RGBA", size)
                x, y, w, h = offsets[index]
                squished = target.resize(
                    (int((112 + w * 1.25) * 0.875), int((112 + h * 1.25) * 0.875)),
                    Image.Resampling.LANCZOS,
                )
                canvas.alpha_composite(
                    squished, (int(14 + x * 0.5), int(20 + y * 1.125))
                )
                canvas.alpha_composite(
                    hand.crop((index * 112, 0, (index + 1) * 112, 112))
                )
            else:
                filename = (
                    f"{index:02d}.png" if kind in {"发射", "杀"} else f"{index}.png"
                )
                with Image.open(ASSET_ROOT / asset / filename) as source:
                    if source.size != size:
                        raise ImageProcessingError(
                            "表情包素材尺寸异常，请重新安装插件。"
                        )
                    overlay = source.convert("RGBA")
                if kind == "发射":
                    canvas = target.copy()
                    canvas.alpha_composite(overlay)
                elif kind == "杀":
                    canvas = Image.new("RGBA", size, "white")
                    x, y, angle = _BEHEAD_LOCS[index]
                    head = target.rotate(
                        -angle, expand=True, resample=Image.Resampling.BICUBIC
                    )
                    canvas.alpha_composite(head, (x, y))
                    canvas.alpha_composite(overlay)
                else:
                    canvas = overlay.copy()
                    if kind == "操你":
                        self_pos = [(116, -8), (109, 3), (130, -10)][index]
                        target_pos = [(2, 177), (12, 172), (6, 158)][index]
                    else:
                        self_pos, target_pos = _LASH_SELF[index], _LASH_TARGET[index]
                    canvas.alpha_composite(commander, self_pos)
                    canvas.alpha_composite(target, target_pos)
            frames.append(_gif_palette(canvas))
        with LimitedBuffer(limits.max_output_bytes) as output:
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
                disposal=2,
                transparency=255,
                background=255,
                optimize=False,
            )
            if time.monotonic() > deadline:
                raise ImageProcessingError("表情包生成超时，请稍后重试。")
            return ProcessedImage(
                output.getvalue(), "GIF", "\n".join(dict.fromkeys(notes))
            )
    except ImageProcessingError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageProcessingError("输入图片尺寸过大。") from exc
    except UnidentifiedImageError as exc:
        raise ImageProcessingError("图片无法解码，请重新发送原图。") from exc
    except (FileNotFoundError, OSError) as exc:
        raise ImageProcessingError(
            "图片或表情包素材无法读取，请重发图片或重新安装插件恢复 resources/memes。"
        ) from exc
    except (ValueError, EOFError) as exc:
        raise ImageProcessingError("图片格式异常，请重新发送原图。") from exc
