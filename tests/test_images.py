# ruff: noqa: I001
# Bootstrap the test package before importing the plugin's relative modules.
import io
import unittest

from tests import PACKAGE  # noqa: F401
from PIL import Image, ImageOps
from pictools_under_test.core.commands import Operation, parse_command
from pictools_under_test.core.image_ops import (
    ImageProcessingError,
    Limits,
    process_image,
)


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def decode(data):
    with Image.open(io.BytesIO(data)) as image:
        loop = image.info.get("loop")
        frames, durations = [], []
        for index in range(image.n_frames):
            image.seek(index)
            frames.append(image.convert("RGBA"))
            durations.append(image.info.get("duration"))
        return frames, durations, loop


def sample_gif(disposal=2, loop=3):
    frames = []
    for position, color in [(0, "red"), (2, "green"), (4, "blue")]:
        frame = Image.new("RGBA", (9, 7))
        frame.paste(color, (position, 1, position + 2, 4))
        frames.append(frame)
    output = io.BytesIO()
    options = {"loop": loop} if loop is not None else {}
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[40, 80, 120],
        disposal=disposal,
        optimize=True,
        **options,
    )
    return output.getvalue()


class CommandTests(unittest.TestCase):
    def test_commands_and_parameters(self):
        self.assertEqual(parse_command("/对称"), Operation("左右翻转"))
        self.assertEqual(parse_command("/调速 2"), Operation("调速", 2))
        self.assertEqual(parse_command("旋转 -45"), Operation("旋转", -45))
        self.assertIsNone(parse_command("反色 这个效果不错"))
        self.assertIsNone(parse_command("左对称", False))
        self.assertEqual(parse_command("/左对称", False), Operation("左对称"))
        for text in ["调速", "调速 0", "调速 nan", "调速 inf", "旋转 361", "调速 啊"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_command(text)


class ImageTests(unittest.TestCase):
    def test_symmetry_preserves_odd_center_and_alpha(self):
        for size in [(5, 3), (4, 4), (1, 1), (1, 5), (5, 1)]:
            image = Image.new("RGBA", size)
            image.putdata([(i * 7, 20, 30, i * 5) for i in range(size[0] * size[1])])
            for name in ["左对称", "右对称", "上对称", "下对称"]:
                with self.subTest(size=size, name=name):
                    frames, _, _ = decode(
                        process_image(png(image), Operation(name)).data
                    )
                    result = frames[0]
                    self.assertEqual(result.size, size)
                    for y in range(size[1]):
                        for x in range(size[0]):
                            sx, sy = x, y
                            if name == "左对称" and x >= (size[0] + 1) // 2:
                                sx = size[0] - 1 - x
                            elif name == "右对称" and x < size[0] // 2:
                                sx = size[0] - 1 - x
                            elif name == "上对称" and y >= (size[1] + 1) // 2:
                                sy = size[1] - 1 - y
                            elif name == "下对称" and y < size[1] // 2:
                                sy = size[1] - 1 - y
                            self.assertEqual(
                                result.getpixel((x, y)), image.getpixel((sx, sy))
                            )

    def test_transforms_keep_alpha(self):
        image = Image.new("RGBA", (3, 2), (10, 20, 30, 77))
        for operation in [Operation("反色"), Operation("灰度"), Operation("上下翻转")]:
            result = decode(process_image(png(image), operation).data)[0][0]
            self.assertEqual(
                result.getchannel("A").tobytes(), image.getchannel("A").tobytes()
            )
        inverted = decode(process_image(png(image), Operation("反色")).data)[0][0]
        self.assertEqual(inverted.getpixel((0, 0)), (245, 235, 225, 77))
        rotated = decode(process_image(png(image), Operation("顺时针")).data)[0][0]
        self.assertEqual(rotated.size, (2, 3))

    def test_exif_orientation_is_applied(self):
        image = Image.new("RGB", (3, 2), "red")
        exif = Image.Exif()
        exif[274] = 6
        output = io.BytesIO()
        image.save(output, format="JPEG", exif=exif)
        result = decode(process_image(output.getvalue(), Operation("灰度")).data)[0][0]
        self.assertEqual(result.size, (2, 3))

    def test_gif_disposal_and_transparency(self):
        for disposal in [1, 2, 3, [1, 2, 3]]:
            with self.subTest(disposal=disposal):
                data = sample_gif(disposal)
                original, durations, loop = decode(data)
                result, out_durations, out_loop = decode(
                    process_image(data, Operation("左右翻转")).data
                )
                self.assertEqual(out_durations, durations)
                self.assertEqual(out_loop, loop)
                self.assertEqual(len(result), len(original))
                for source, actual in zip(original, result):
                    expected = ImageOps.mirror(source)
                    self.assertEqual(
                        actual.getchannel("A").tobytes(),
                        expected.getchannel("A").tobytes(),
                    )
                    for a, b in zip(actual.getdata(), expected.getdata()):
                        if b[3]:
                            self.assertEqual(a, b)

    def test_reverse_moves_durations_with_frames(self):
        data = sample_gif()
        original, durations, _ = decode(data)
        frames, actual_durations, loop = decode(
            process_image(data, Operation("倒放")).data
        )
        self.assertEqual(actual_durations, durations[::-1])
        self.assertEqual(loop, 3)
        for frame, expected in zip(frames, reversed(original)):
            self.assertEqual(
                frame.getchannel("A").tobytes(), expected.getchannel("A").tobytes()
            )
            for actual, wanted in zip(frame.getdata(), expected.getdata()):
                if wanted[3]:
                    self.assertEqual(actual, wanted)

    def test_loop_absence_and_speed_limit(self):
        data = sample_gif(loop=None)
        result = process_image(data, Operation("调速", 10))
        _, durations, loop = decode(result.data)
        self.assertIsNone(loop)
        self.assertEqual(durations, [20, 20, 20])
        self.assertIn("20ms", result.note)
        _, durations, _ = decode(process_image(data, Operation("调速", 2)).data)
        self.assertEqual(durations, [20, 40, 60])

    def test_single_frame_gif_stays_readable(self):
        source = Image.new("RGBA", (3, 3), (255, 0, 0, 0))
        source.putpixel((1, 1), (255, 0, 0, 255))
        output = io.BytesIO()
        source.save(output, format="GIF", duration=80)
        result = process_image(output.getvalue(), Operation("左对称"))
        frames, durations, loop = decode(result.data)
        self.assertEqual(result.format, "GIF")
        self.assertEqual(len(frames), 1)
        self.assertEqual(durations, [80])
        self.assertIsNone(loop)
        self.assertEqual(frames[0].getpixel((0, 0))[3], 0)

    def test_animated_png_is_explicitly_rejected(self):
        output = io.BytesIO()
        first = Image.new("RGBA", (2, 2), "red")
        first.save(
            output,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGBA", (2, 2), "blue")],
            duration=100,
        )
        with self.assertRaisesRegex(ImageProcessingError, "转换为 GIF"):
            process_image(output.getvalue(), Operation("反色"))

    def test_limits_and_bad_inputs(self):
        gif = sample_gif()
        for limits in [
            Limits(max_frames=2),
            Limits(max_pixels=50),
            Limits(max_total_pixels=100),
            Limits(max_output_bytes=10),
            Limits(timeout=-1),
        ]:
            with self.subTest(limits=limits), self.assertRaises(ImageProcessingError):
                process_image(gif, Operation("左对称"), limits)
        for data, operation in [
            (b"not an image", Operation("左对称")),
            (png(Image.new("RGB", (2, 2))), Operation("倒放")),
        ]:
            with self.assertRaises(ImageProcessingError):
                process_image(data, operation)


if __name__ == "__main__":
    unittest.main()
