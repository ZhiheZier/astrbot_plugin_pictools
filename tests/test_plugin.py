import asyncio
import base64
import io
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from tests import ROOT

# Use the installed AstrBot API with an isolated data directory.
os.environ["ASTRBOT_ROOT"] = str(ROOT / ".test_runtime")
sys.path.insert(0, str(ROOT.parents[2]))

import astrbot.api.message_components as Comp  # noqa: E402
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember  # noqa: E402
from astrbot.core.platform.message_type import MessageType  # noqa: E402
from astrbot.core.platform.platform_metadata import PlatformMetadata  # noqa: E402
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (  # noqa: E402
    AiocqhttpMessageEvent,
)
from pictools_under_test.core.commands import Operation  # noqa: E402
from pictools_under_test.main import PendingAction, PicToolsPlugin  # noqa: E402

from tests.test_images import sample_gif  # noqa: E402


class FakeEvent:
    def __init__(self, chain, user="123", group="456", platform="aiocqhttp"):
        self.chain = chain
        self.user = user
        self.group = group
        self.platform = platform
        self.unified_msg_origin = f"{platform}:GroupMessage:{group}"
        self.stopped = False
        self.bot = SimpleNamespace(call_action=AsyncMock())

    def get_messages(self):
        return self.chain

    def get_sender_id(self):
        return self.user

    def get_group_id(self):
        return self.group

    def get_self_id(self):
        return "999"

    def get_platform_name(self):
        return self.platform

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text

    def chain_result(self, chain):
        return chain


def image_component():
    output = io.BytesIO()
    Image.new("RGBA", (3, 3), (255, 0, 0, 100)).save(output, format="PNG")
    return Comp.Image.fromBytes(output.getvalue())


async def handle(plugin, event):
    return [result async for result in plugin.handle_message(event)]


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = PicToolsPlugin(SimpleNamespace(), {"cooldown_seconds": 0})

    async def asyncTearDown(self):
        await self.plugin.terminate()

    async def test_emoji_combination_sends_qq_sticker_without_avatar_or_upload(self):
        pending = FakeEvent([Comp.Plain("/左对称")])
        await handle(self.plugin, pending)
        source = base64.b64decode(image_component().file.removeprefix("base64://"))
        self.plugin.config["match_mode"] = False
        event = FakeEvent([Comp.Plain("😀+😂")])
        with patch.object(
            self.plugin.reader, "read", AsyncMock(return_value=source)
        ) as read:
            with patch.object(
                self.plugin, "_find_image", AsyncMock(side_effect=AssertionError)
            ):
                result = await handle(self.plugin, event)
            self.assertTrue(
                read.await_args.args[0].startswith("https://www.gstatic.com/")
            )
        self.assertTrue(event.stopped)
        self.assertEqual(result, [])
        event.bot.call_action.assert_awaited_once()
        sent = event.bot.call_action.await_args
        self.assertEqual(sent.args, ("send_group_msg",))
        self.assertEqual(sent.kwargs["group_id"], 456)
        self.assertEqual(sent.kwargs["self_id"], "999")
        self.assertEqual(len(sent.kwargs["message"]), 1)
        segment = sent.kwargs["message"][0]
        self.assertEqual(segment["type"], "image")
        self.assertEqual(segment["data"]["sub_type"], 1)
        self.assertEqual(segment["data"]["summary"], "[合成表情]")
        data = base64.b64decode(segment["data"]["file"].removeprefix("base64://"))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.format, "PNG")
        self.assertIn(self.plugin._key(pending), self.plugin.pending)
        self.assertEqual(self.plugin.active, 0)

    async def test_emoji_sticker_private_routing_and_send_failure(self):
        source = base64.b64decode(image_component().file.removeprefix("base64://"))
        event = FakeEvent([Comp.Plain("❤️ + 🔥")], group="")
        with patch.object(self.plugin.reader, "read", AsyncMock(return_value=source)):
            self.assertEqual(await handle(self.plugin, event), [])
            sent = event.bot.call_action.await_args
            self.assertEqual(sent.args, ("send_private_msg",))
            self.assertEqual(sent.kwargs["user_id"], 123)
            self.assertNotIn("group_id", sent.kwargs)
            self.assertEqual(sent.kwargs["message"][0]["data"]["sub_type"], 1)
            event.bot.call_action.side_effect = RuntimeError("send failed")
            with patch("pictools_under_test.main.logger.exception"):
                result = await handle(self.plugin, event)
        self.assertIn("图片处理失败", result[0])
        self.assertEqual(self.plugin.active, 0)
        self.assertFalse(self.plugin.in_flight)

    async def test_emoji_other_platform_still_returns_image(self):
        source = base64.b64decode(image_component().file.removeprefix("base64://"))
        event = FakeEvent([Comp.Plain("😀+😂")], platform="qq_official")
        with patch.object(self.plugin.reader, "read", AsyncMock(return_value=source)):
            result = await handle(self.plugin, event)
        self.assertIsInstance(result[0][0], Comp.Image)
        event.bot.call_action.assert_not_awaited()

    async def test_emoji_errors_release_capacity_and_preserve_pending_upload(self):
        from pictools_under_test.core.media_io import MediaInputError

        pending = FakeEvent([Comp.Plain("/摸头")])
        await handle(self.plugin, pending)
        event = FakeEvent([Comp.Plain("😀+😂")])
        with patch.object(
            self.plugin.reader,
            "read",
            AsyncMock(side_effect=MediaInputError("download failed")),
        ):
            result = await handle(self.plugin, event)
        self.assertIn("www.gstatic.com", result[0])
        self.assertEqual(self.plugin.active, 0)
        self.assertFalse(self.plugin.in_flight)
        self.assertIn(self.plugin._key(pending), self.plugin.pending)
        for text in ("😀+", "/emoji合成 😀 😂", "表情合成 😀+😂", "/emoji 😀😂"):
            event = FakeEvent([Comp.Plain(text)])
            with patch.object(self.plugin.reader, "read", AsyncMock()) as read:
                self.assertEqual(await handle(self.plugin, event), [])
                read.assert_not_awaited()
            self.assertFalse(event.stopped)
            self.assertIn(self.plugin._key(pending), self.plugin.pending)

    async def test_emoji_respects_permissions_cooldown_and_concurrency(self):
        event = FakeEvent([Comp.Plain("😀+😂")])
        self.plugin.config["allowed_users"] = ["other"]
        self.assertEqual(await handle(self.plugin, event), [])
        self.assertFalse(event.stopped)
        self.plugin.config["allowed_users"] = []
        self.plugin.active = 2
        self.assertIn("繁忙", (await handle(self.plugin, event))[0])
        self.plugin.active = 0
        self.plugin.config["cooldown_seconds"] = 3
        source = base64.b64decode(image_component().file.removeprefix("base64://"))
        with patch.object(self.plugin.reader, "read", AsyncMock(return_value=source)):
            await handle(self.plugin, event)
        self.assertIn("太快", (await handle(self.plugin, event))[0])

    async def test_single_image_memes_and_pending_upload(self):
        for name in ["摸头", "发射"]:
            event = FakeEvent([Comp.Plain("/" + name), image_component()])
            result = await handle(self.plugin, event)
            self.assertIsInstance(result[0][-1], Comp.Image)
            data = base64.b64decode(result[0][-1].file.removeprefix("base64://"))
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.format, "GIF")
                self.assertGreater(image.n_frames, 1)
        pending = FakeEvent([Comp.Plain("/摸头")])
        await handle(self.plugin, pending)
        result = await handle(self.plugin, FakeEvent([image_component()]))
        self.assertIsInstance(result[0][-1], Comp.Image)
        self.assertNotIn(self.plugin._key(pending), self.plugin.pending)

    async def test_required_avatar_targets_and_double_avatar_roles(self):
        encoded = image_component().file.removeprefix("base64://")
        source = base64.b64decode(encoded)
        for name in ["杀", "操你", "抽你"]:
            event = FakeEvent([Comp.Plain("/" + name), Comp.At(qq="999")])
            result = await handle(self.plugin, event)
            self.assertIn("目标用户", result[0])
            event.chain = [Comp.Plain("/" + name), Comp.At(qq="999"), Comp.At(qq="777")]
            with patch.object(
                self.plugin.reader, "read", AsyncMock(return_value=source)
            ) as reader:
                result = await handle(self.plugin, event)
                self.assertIn("nk=777", reader.await_args_list[0].args[0])
                if name in {"操你", "抽你"}:
                    self.assertEqual(reader.await_count, 2)
                    self.assertIn("nk=123", reader.await_args_list[1].args[0])
                else:
                    self.assertEqual(reader.await_count, 1)
            self.assertIsInstance(result[0][-1], Comp.Image)

    async def test_avatar_memes_respect_platform_and_avatar_setting(self):
        event = FakeEvent(
            [Comp.Plain("/操你"), Comp.At(qq="777")], platform="qq_official"
        )
        self.assertIn("OneBot", (await handle(self.plugin, event))[0])
        event.platform = "aiocqhttp"
        self.plugin.config["enable_at_avatar"] = False
        self.assertIn("已关闭", (await handle(self.plugin, event))[0])
        self.assertEqual(self.plugin.active, 0)
        self.assertFalse(self.plugin.in_flight)

    async def test_reports_need_no_image_and_preserve_pending_upload(self):
        await handle(self.plugin, FakeEvent([Comp.Plain("/左对称")]))
        for command in ["/喜报 今天又收到了喜报", "/悲报 假期结束了"]:
            event = FakeEvent([Comp.Plain(command)])
            with patch.object(self.plugin.reader, "read", AsyncMock()) as read:
                result = await handle(self.plugin, event)
                read.assert_not_awaited()
            self.assertTrue(event.stopped)
            self.assertIsInstance(result[0][0], Comp.Image)
            encoded = result[0][0].file.removeprefix("base64://")
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
                self.assertEqual(image.size, (1385, 1035))
            self.assertIn(self.plugin._key(event), self.plugin.pending)
        result = await handle(self.plugin, FakeEvent([Comp.Plain("/喜报")]))
        self.assertIn("用法", result[0])
        self.assertEqual(self.plugin.active, 0)

    async def test_reports_share_permissions_cooldown_and_concurrency(self):
        event = FakeEvent([Comp.Plain("/喜报 今天放假")])
        self.plugin.config["allowed_users"] = ["other"]
        self.assertEqual(await handle(self.plugin, event), [])
        self.assertFalse(event.stopped)
        self.plugin.config["allowed_users"] = []
        self.plugin.active = 2
        self.assertIn("繁忙", (await handle(self.plugin, event))[0])
        self.plugin.active = 0
        self.plugin.config["cooldown_seconds"] = 3
        await handle(self.plugin, event)
        self.assertIn("太快", (await handle(self.plugin, event))[0])

    async def test_real_astrbot_event_and_onebot_gif_serialization(self):
        message = AstrBotMessage()
        message.type = MessageType.GROUP_MESSAGE
        message.group_id = "456"
        message.sender = MessageMember(user_id="123", nickname="Tester")
        message.self_id = "999"
        message.message_id = "1"
        message.message = [Comp.Plain("/倒放"), Comp.Image.fromBytes(sample_gif())]
        message.message_str = "/倒放"
        event = AiocqhttpMessageEvent(
            "/倒放",
            message,
            PlatformMetadata("aiocqhttp", "test", "test-bot"),
            "456",
            SimpleNamespace(call_action=AsyncMock()),
        )
        results = await handle(self.plugin, event)
        self.assertTrue(event.is_stopped())
        segments = await AiocqhttpMessageEvent._parse_onebot_json(results[0])
        self.assertEqual(segments[0]["type"], "image")
        encoded = segments[0]["data"]["file"].removeprefix("base64://")
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as gif:
            self.assertEqual(gif.format, "GIF")
            self.assertEqual(gif.n_frames, 3)
            self.assertEqual(gif.info["duration"], 120)

    async def test_pending_is_scoped_by_user_and_session(self):
        command = FakeEvent([Comp.Plain("/左对称")])
        self.assertIn("120", (await handle(self.plugin, command))[0])
        key = self.plugin._key(command)
        unrelated = FakeEvent([Comp.Plain("普通聊天")])
        self.assertEqual(await handle(self.plugin, unrelated), [])
        self.assertFalse(unrelated.stopped)
        for user, group in [("124", "456"), ("123", "457")]:
            event = FakeEvent([image_component()], user=user, group=group)
            self.assertEqual(await handle(self.plugin, event), [])
            self.assertFalse(event.stopped)
        self.assertIn(key, self.plugin.pending)
        uploaded = FakeEvent([image_component()])
        result = await handle(self.plugin, uploaded)
        self.assertIsInstance(result[0][0], Comp.Image)
        self.assertTrue(uploaded.stopped)
        self.assertNotIn(key, self.plugin.pending)
        result_data = base64.b64decode(result[0][0].file.removeprefix("base64://"))
        with Image.open(io.BytesIO(result_data)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 100))

    async def test_pending_expiry_cancel_and_replacement(self):
        event = FakeEvent([Comp.Plain("/左对称")])
        await handle(self.plugin, event)
        key = self.plugin._key(event)
        await handle(self.plugin, FakeEvent([Comp.Plain("/反色")]))
        self.assertEqual(self.plugin.pending[key].operation.name, "反色")
        result = await handle(self.plugin, FakeEvent([Comp.Plain("/取消图片处理")]))
        self.assertIn("已取消", result[0])
        self.assertNotIn(key, self.plugin.pending)
        self.plugin.pending[key] = PendingAction(
            Operation("反色"), time.monotonic() - 1
        )
        uploaded = FakeEvent([image_component()])
        self.assertEqual(await handle(self.plugin, uploaded), [])
        self.assertFalse(uploaded.stopped)

    async def test_reply_and_source_priority(self):
        direct = image_component()
        quoted = Comp.Image.fromURL("https://example.com/quoted.gif")
        event = FakeEvent(
            [
                Comp.At(qq="999"),
                Comp.At(qq="1234"),
                Comp.Reply(id=1, chain=[quoted]),
                direct,
            ]
        )
        self.assertIs(await self.plugin._find_image(event), direct)
        event.chain.remove(direct)
        self.assertEqual(await self.plugin._find_image(event), quoted)
        event.chain = [Comp.At(qq="999"), Comp.At(qq="1234"), Comp.Plain("/反色")]
        self.assertIn("nk=1234", (await self.plugin._find_image(event)).file)
        event.chain = [Comp.At(qq="999")]
        self.assertIsNone(await self.plugin._find_image(event))
        event.chain = [Comp.At(qq="1234")]
        event.platform = "qq_official"
        self.assertIsNone(await self.plugin._find_image(event))

    async def test_onebot_reply_and_file_id_fallback(self):
        source = image_component().file
        event = FakeEvent([Comp.Reply(id=7)])
        event.bot.call_action.return_value = {
            "data": {"message": [{"type": "image", "data": {"file": source}}]}
        }
        image = await self.plugin._find_image(event)
        self.assertEqual(image.file, source)
        event.bot.call_action.assert_awaited_once_with("get_msg", message_id=7)
        event.bot.call_action.reset_mock()
        event.bot.call_action.return_value = {"url": "https://example.com/image.gif"}
        with patch.object(
            self.plugin.reader, "read", AsyncMock(return_value=b"gif")
        ) as read:
            self.assertEqual(
                await self.plugin._read_image(event, Comp.Image(file="hash.image")),
                b"gif",
            )
            read.assert_awaited_once_with("https://example.com/image.gif")
        event.bot.call_action.assert_awaited_once_with("get_image", file="hash.image")

    async def test_mentions_do_not_break_command_parsing(self):
        event = FakeEvent([Comp.At(qq="999"), Comp.Plain("/反色"), image_component()])
        result = await handle(self.plugin, event)
        self.assertIsInstance(result[0][0], Comp.Image)
        self.plugin.config["match_mode"] = False
        event = FakeEvent([Comp.Plain("反色"), image_component()])
        self.assertEqual(await handle(self.plugin, event), [])
        self.assertFalse(event.stopped)

    async def test_permissions_busy_cooldown_and_errors(self):
        self.plugin.config["allowed_groups"] = ["other"]
        event = FakeEvent([Comp.Plain("/反色"), image_component()])
        self.assertEqual(await handle(self.plugin, event), [])
        self.assertFalse(event.stopped)
        self.plugin.config["allowed_groups"] = []
        self.plugin.config["allowed_users"] = ["other"]
        self.assertEqual(await handle(self.plugin, event), [])
        self.plugin.config["allowed_users"] = []
        self.plugin.active = 2
        self.assertIn("繁忙", (await handle(self.plugin, event))[0])
        self.plugin.active = 0
        self.plugin.config["cooldown_seconds"] = 3
        await handle(self.plugin, event)
        self.assertIn("太快", (await handle(self.plugin, event))[0])
        result = await handle(self.plugin, FakeEvent([Comp.Plain("/调速 nan")]))
        self.assertIn("范围", result[0])

    async def test_concurrent_same_user_is_rejected_and_capacity_released(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_read(_):
            entered.set()
            await release.wait()
            return b"invalid"

        event = FakeEvent([Comp.Plain("/反色"), image_component()])
        with patch.object(self.plugin.reader, "read", delayed_read):
            task = asyncio.create_task(handle(self.plugin, event))
            await entered.wait()
            self.assertIn("上一张", (await handle(self.plugin, event))[0])
            release.set()
            self.assertIn("无法解码", (await task)[0])
        self.assertEqual(self.plugin.active, 0)
        self.assertFalse(self.plugin.in_flight)


if __name__ == "__main__":
    unittest.main()
