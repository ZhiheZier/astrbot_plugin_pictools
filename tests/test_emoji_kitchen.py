# ruff: noqa: I001
# Bootstrap the test package before importing the plugin's relative modules.
import gzip
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import PACKAGE  # noqa: F401
from pictools_under_test.core.commands import Operation, parse_command
from pictools_under_test.core.emoji_kitchen import _emoji_index, emoji_kitchen_url
from pictools_under_test.core.image_ops import ImageProcessingError


class EmojiKitchenTests(unittest.TestCase):
    def tearDown(self):
        _emoji_index.cache_clear()

    def test_missing_emoji_dependency_is_visible_during_plugin_import(self):
        commands_path = Path(__file__).resolve().parents[1] / "core" / "commands.py"
        with patch.dict("sys.modules", {"emoji": None}):
            with self.assertRaises(ModuleNotFoundError) as error:
                runpy.run_path(str(commands_path))
        self.assertEqual(error.exception.name, "emoji")

    def test_bare_emoji_equations_trigger_with_or_without_command_matching(self):
        for text, expected in [
            ("😀+😂", "😀 😂"),
            (" 😀 + 😂 ", "😀 😂"),
            ("😀＋😂", "😀 😂"),
            ("❤️+🔥", "❤️ 🔥"),
            ("❤︎+🔥", "❤︎ 🔥"),
            ("👩🏽‍💻+🤖", "👩🏽‍💻 🤖"),
            ("😀+😀", "😀 😀"),
        ]:
            for mode in (True, False):
                with self.subTest(text=text, mode=mode):
                    self.assertEqual(
                        parse_command(text, mode), Operation("emoji合成", text=expected)
                    )

    def test_bare_trigger_does_not_capture_ordinary_chat(self):
        for text in [
            "1+2",
            "文字+文字",
            "😀+文字",
            "文字+😂",
            "😀😂",
            "😀 😂",
            "试试 😀+😂",
            "😀+😂 真好玩",
            "😀+😂+🥳",
            "😀++😂",
            "+😀😂",
            "😀 +",
            "+ 😂",
            "/😀+😂",
            "😀,😂",
            "[CQ:face,id=1]+😂",
            "😀" * 129 + "+😂",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(parse_command(text))

    def test_legacy_emoji_commands_are_ignored(self):
        for alias in ("emoji合成", "表情合成", "emoji"):
            for prefix in ("", "/"):
                for content in ("", "😀", "😀 😂", "😀+😂", "😀😂", "👩🏽‍💻+🤖"):
                    for mode in (True, False):
                        command = f"{prefix}{alias} {content}"
                        with self.subTest(command=command, mode=mode):
                            self.assertIsNone(parse_command(command, mode))

    def test_known_pair_reversed_pair_and_self_pair(self):
        expected = "https://www.gstatic.com/android/keyboard/emojikitchen/20201001/u1f600/u1f600_u1f602.png"
        self.assertEqual(emoji_kitchen_url("😀", "😂"), expected)
        self.assertEqual(emoji_kitchen_url("😂", "😀"), expected)
        self.assertIn("u1f600_u1f600.png", emoji_kitchen_url("😀", "😀"))

    def test_variation_selector_and_upstream_alias_mapping(self):
        expected = "https://www.gstatic.com/android/keyboard/emojikitchen/20230821/u2764-ufe0f/u2764-ufe0f_u1f525.png"
        self.assertEqual(emoji_kitchen_url("❤️", "🔥"), expected)
        self.assertEqual(emoji_kitchen_url("❤", "🔥"), expected)
        self.assertEqual(emoji_kitchen_url("❤︎", "🔥"), expected)
        self.assertEqual(emoji_kitchen_url("🔴", "🔥"), expected)

    def test_unsupported_emoji_and_missing_pair(self):
        with self.assertRaisesRegex(ImageProcessingError, "暂不支持"):
            emoji_kitchen_url("🇨🇳", "😀")
        with patch(
            "pictools_under_test.core.emoji_kitchen._emoji_index",
            return_value=({}, {"1f600": "1f600", "1f602": "1f602"}),
        ):
            with self.assertRaisesRegex(ImageProcessingError, "暂无合成结果"):
                emoji_kitchen_url("😀", "😂")

    def test_missing_or_corrupt_index_has_a_readable_error(self):
        _emoji_index.cache_clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json.gz"
            with patch("pictools_under_test.core.emoji_kitchen.INDEX_PATH", path):
                with self.assertRaisesRegex(ImageProcessingError, "索引无法读取"):
                    emoji_kitchen_url("😀", "😂")
                path.write_bytes(gzip.compress(b"not-json"))
                with self.assertRaisesRegex(ImageProcessingError, "索引无法读取"):
                    emoji_kitchen_url("😀", "😂")

    def test_invalid_asset_record_cannot_change_host_or_path(self):
        records = {"1f602|1f600": [20201001, "../../secret", "1f602"]}
        normalized = {"1f600": "1f600", "1f602": "1f602"}
        with patch(
            "pictools_under_test.core.emoji_kitchen._emoji_index",
            return_value=(records, normalized),
        ):
            with self.assertRaisesRegex(ImageProcessingError, "组合记录异常"):
                emoji_kitchen_url("😀", "😂")
