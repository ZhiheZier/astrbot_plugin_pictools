# ruff: noqa: I001
# Bootstrap the test package before importing the plugin's relative modules.
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import ROOT
from PIL import Image
from pictools_under_test.core.commands import parse_command
from pictools_under_test.core.image_ops import ImageProcessingError, Limits
from pictools_under_test.core.memes import (
    MEME_SPECS,
    _circle_avatar,
    _face_center,
    generate_meme,
)
from tests.test_images import sample_gif


def avatar_bytes(color, size=(80, 100)):
    output = io.BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return output.getvalue()


class MemeTests(unittest.TestCase):
    def test_command_aliases(self):
        for alias, expected in {
            "摸头杀": "摸头",
            "砍头": "杀",
            "撅人": "操你",
            "鞭笞": "抽你",
            "摸头": "摸头",
            "发射": "发射",
            "杀": "杀",
            "操你": "操你",
            "抽你": "抽你",
        }.items():
            with self.subTest(alias=alias):
                self.assertEqual(parse_command("/" + alias).name, expected)
                self.assertIsNone(parse_command(alias, False))
        self.assertIsNone(parse_command("摸头 这是普通聊天"))

    def test_all_five_animations_and_template_timing(self):
        for kind, (_, count, size, duration) in MEME_SPECS.items():
            with self.subTest(kind=kind):
                result = generate_meme(kind, avatar_bytes("red"), avatar_bytes("blue"))
                self.assertEqual(result.format, "GIF")
                with Image.open(io.BytesIO(result.data)) as image:
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.n_frames, count)
                    self.assertEqual(image.info["loop"], 0)
                    for index in range(image.n_frames):
                        image.seek(index)
                        self.assertEqual(image.info["duration"], duration)
                    image.seek(0)
                    frame = image.convert("RGB")
                    if kind in {"操你", "抽你"}:
                        self.assertIn((255, 0, 0), frame.getdata())
                        self.assertIn((0, 0, 255), frame.getdata())

    def test_avatar_circle_keeps_existing_alpha(self):
        circle = _circle_avatar(Image.new("RGBA", (90, 70), (255, 0, 0, 70)), 22)
        self.assertEqual(circle.getpixel((11, 11))[3], 70)
        self.assertEqual(circle.getpixel((0, 0))[3], 0)

    def test_dual_roles_and_first_frame_note(self):
        result = generate_meme("操你", avatar_bytes("red"), avatar_bytes("blue"))
        with Image.open(io.BytesIO(result.data)) as image:
            frame = image.convert("RGB")
            self.assertEqual(frame.getpixel((58, 233)), (255, 0, 0))
            self.assertEqual(frame.getpixel((177, 53)), (0, 0, 255))
        result = generate_meme("摸头", sample_gif())
        self.assertIn("首帧", result.note)

    def test_invalid_input_limits_and_missing_assets(self):
        data = avatar_bytes("red")
        for limits in [
            Limits(max_frames=2),
            Limits(max_pixels=10),
            Limits(max_total_pixels=100),
            Limits(max_output_bytes=10),
            Limits(timeout=-1),
        ]:
            with self.subTest(limits=limits), self.assertRaises(ImageProcessingError):
                generate_meme("摸头", data, limits=limits)
        for kind, target in [("未知", data), ("摸头", b"broken"), ("操你", data)]:
            with self.subTest(kind=kind), self.assertRaises(ImageProcessingError):
                generate_meme(kind, target)
        with patch(
            "pictools_under_test.core.memes.ASSET_ROOT", ROOT / "nonexistent-assets"
        ):
            with self.assertRaises(ImageProcessingError):
                generate_meme("摸头", data)

    def test_face_crop_fallback_and_narrow_input(self):
        with patch.dict(sys.modules, {"cv2": None}):
            result = generate_meme("发射", avatar_bytes("red", (1, 1000)))
        self.assertIn("中心裁剪", result.note)
        with Image.open(io.BytesIO(result.data)) as image:
            self.assertEqual(image.n_frames, 13)
            self.assertEqual(image.size, (160, 97))

    def test_face_center_selects_largest_detection(self):
        cascade = SimpleNamespace(
            empty=lambda: False,
            detectMultiScale=lambda *a, **kw: [(0, 0, 20, 20), (40, 50, 30, 30)],
        )
        cv = SimpleNamespace(
            CascadeClassifier=lambda path: cascade,
            equalizeHist=lambda gray: gray,
            data=SimpleNamespace(haarcascades="unused"),
        )
        with patch.dict(sys.modules, {"cv2": cv}):
            center, note = _face_center(Image.new("RGBA", (100, 100)))
        self.assertEqual(center, (0.55, 0.65))
        self.assertFalse(note)

    def test_real_opencv_cascades_load_when_available(self):
        with patch.object(sys, "path", [str(ROOT / ".dev_deps"), *sys.path]):
            try:
                import cv2  # noqa: F401
            except ImportError:
                self.skipTest(
                    "OpenCV dependency is not installed in the test environment"
                )
            center, note = _face_center(Image.new("RGBA", (100, 100), "white"))
        self.assertIsNone(center)
        self.assertEqual(note, "未检测到人脸，已按图片中心裁剪。")


if __name__ == "__main__":
    unittest.main()
