# ruff: noqa: I001
# Bootstrap the test package before importing the plugin's relative modules.
import io
import unittest
from unittest.mock import patch

from tests import PACKAGE  # noqa: F401
from PIL import Image, ImageChops
from pictools_under_test.core.commands import Operation, parse_command
from pictools_under_test.core.image_ops import ImageProcessingError, Limits
from pictools_under_test.core.reports import BACKGROUND_ROOT, generate_report


class ReportTests(unittest.TestCase):
    def test_commands_preserve_content_and_respect_prefix_mode(self):
        self.assertEqual(
            parse_command("/喜报 今天收到喜报  太开心了\n第二行"),
            Operation("喜报", text="今天收到喜报  太开心了\n第二行"),
        )
        self.assertEqual(
            parse_command("悲报 放假结束"), Operation("悲报", text="放假结束")
        )
        self.assertIsNone(parse_command("喜报 今天放假", False))
        self.assertIsNone(parse_command("今天有个喜报"))
        self.assertEqual(parse_command("/悲报 假期结束", False).text, "假期结束")
        for text in ["/喜报", "/悲报  ", "喜报 " + "字" * 501]:
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                parse_command(text)

    def test_both_posters_have_readable_images_and_distinct_styles(self):
        for kind in ["喜报", "悲报"]:
            result = generate_report(kind, "测试中文与 English\n第二行：今天的消息")
            self.assertEqual(result.format, "PNG")
            with Image.open(io.BytesIO(result.data)) as image:
                self.assertEqual(image.size, (1385, 1035))
                self.assertEqual(image.format, "PNG")
                grayscale = image.convert("L").convert("RGB")
                self.assertEqual(image.tobytes() == grayscale.tobytes(), kind == "悲报")
                foreground = (255, 0, 0) if kind == "喜报" else (0, 0, 0)
                self.assertIn(foreground, image.crop((138, 248, 1246, 848)).getdata())
                filename = "congrats.jpg" if kind == "喜报" else "uncongrats.jpg"
                with Image.open(BACKGROUND_ROOT / filename) as background:
                    difference = ImageChops.difference(image, background.convert("RGB"))
                    changed = difference.getbbox()
                    self.assertIsNotNone(changed)
                    self.assertGreaterEqual(changed[0], 138)
                    self.assertGreaterEqual(changed[1], 248)
                    self.assertLessEqual(changed[2], 1246)
                    self.assertLessEqual(changed[3], 848)

    def test_long_text_and_manual_line_breaks(self):
        for text in ["中文排版" * 125, "hello World " * 40, "第一行\n\n第三行"]:
            with self.subTest(text=text[:10]):
                result = generate_report("喜报", text)
                with Image.open(io.BytesIO(result.data)) as image:
                    self.assertEqual(image.size, (1385, 1035))
        with self.assertRaisesRegex(ImageProcessingError, "换行过多"):
            generate_report("悲报", "内容\n" * 80)

    def test_validation_and_resource_limits(self):
        for kind, text in [
            ("喜报", ""),
            ("悲报", "字" * 501),
            ("其他", "文字"),
            ("喜报", "坏\x00字符"),
        ]:
            with self.subTest(kind=kind), self.assertRaises(ImageProcessingError):
                generate_report(kind, text)
        for limits in [
            Limits(max_pixels=10),
            Limits(max_output_bytes=10),
            Limits(timeout=-1),
        ]:
            with self.subTest(limits=limits), self.assertRaises(ImageProcessingError):
                generate_report("喜报", "测试", limits=limits)
        with patch("pictools_under_test.core.reports.FONT_PATH", "missing-font.otf"):
            with self.assertRaisesRegex(ImageProcessingError, "字体无法读取"):
                generate_report("悲报", "测试")

    def test_missing_background_has_actionable_error(self):
        with patch("pictools_under_test.core.reports.Image.open", side_effect=OSError):
            with self.assertRaisesRegex(ImageProcessingError, "背景无法读取"):
                generate_report("喜报", "测试")


if __name__ == "__main__":
    unittest.main()
