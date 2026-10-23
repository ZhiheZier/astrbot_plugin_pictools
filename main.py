"""AstrBot image tools for NapCat / OneBot v11."""

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

try:
    from astrbot.core.utils.path_utils import get_astrbot_temp_path
except ModuleNotFoundError:
    # AstrBot 4.22 uses astrbot_path instead of path_utils.
    from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .core.commands import HELP, Operation, parse_command
from .core.emoji_kitchen import emoji_kitchen_url
from .core.image_ops import ImageProcessingError, Limits, process_image
from .core.media_io import MediaInputError, MediaReader
from .core.memes import MEME_SPECS, generate_meme
from .core.reports import generate_report


@dataclass(frozen=True)
class PendingAction:
    operation: Operation
    expires: float


class PicToolsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.pending: dict[tuple[str, str], PendingAction] = {}
        self.last_request: OrderedDict[tuple[str, str], float] = OrderedDict()
        self.active = 0
        self.in_flight: set[tuple[str, str]] = set()
        self.closed = False
        self.workers: set[asyncio.Task] = set()
        self.limits = Limits(
            max_pixels=self._integer("max_pixels", 16_000_000, 1),
            max_frames=self._integer("max_frames", 200, 1),
            max_total_pixels=self._integer("max_total_pixels", 24_000_000, 1),
            max_output_bytes=self._integer("max_file_mb", 20, 1) * 1024 * 1024,
            timeout=self._integer("process_timeout", 30, 1),
        )
        self.reader = MediaReader(
            max_bytes=self.limits.max_output_bytes,
            timeout=self._integer("download_timeout", 30, 1),
            trusted_roots=(Path(get_astrbot_temp_path()),),
        )

    def _integer(self, key: str, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(self.config.get(key, default)))
        except (ValueError, TypeError):
            return default

    def _allowed(self, event: AstrMessageEvent) -> bool:
        groups = {str(item) for item in self.config.get("allowed_groups", [])}
        users = {str(item) for item in self.config.get("allowed_users", [])}
        return (not users or event.get_sender_id() in users) and (
            not groups or not event.get_group_id() or event.get_group_id() in groups
        )

    @staticmethod
    def _key(event: AstrMessageEvent) -> tuple[str, str]:
        return event.unified_msg_origin, event.get_sender_id()

    @staticmethod
    def _text(event: AstrMessageEvent) -> str:
        # Plain components exclude synthetic mention labels in message_str.
        return " ".join(
            part.text for part in event.get_messages() if isinstance(part, Comp.Plain)
        ).strip()

    def _prune(self, now: float):
        self.pending = {
            key: action for key, action in self.pending.items() if action.expires > now
        }
        while self.last_request:
            key, timestamp = next(iter(self.last_request.items()))
            if now - timestamp < 3600 and len(self.last_request) <= 4096:
                break
            self.last_request.pop(key)

    @staticmethod
    def _first_image(chain) -> Comp.Image | None:
        return next((part for part in chain if isinstance(part, Comp.Image)), None)

    async def _find_image(self, event: AstrMessageEvent) -> Comp.Image | None:
        chain = event.get_messages()
        if image := self._first_image(chain):
            return image
        for part in chain:
            if not isinstance(part, Comp.Reply):
                continue
            if image := self._first_image(part.chain or []):
                return image
            if event.get_platform_name() == "aiocqhttp":
                try:
                    reply = await asyncio.wait_for(
                        event.bot.call_action("get_msg", message_id=int(part.id)), 10
                    )
                    payload = reply.get("data", reply)
                    segments = payload.get("message", [])
                    if isinstance(segments, list):
                        for segment in segments:
                            if segment.get("type") == "image":
                                info = segment.get("data", {})
                                return Comp.Image(
                                    file=info.get("file", ""), url=info.get("url", "")
                                )
                except Exception as exc:
                    logger.debug(
                        "[pictools] Could not resolve reply: %s", type(exc).__name__
                    )
        if (
            self.config.get("enable_at_avatar", True)
            and event.get_platform_name() == "aiocqhttp"
        ):
            for part in chain:
                if isinstance(part, Comp.At):
                    qq = str(part.qq)
                    if qq.isascii() and qq.isdigit() and qq != str(event.get_self_id()):
                        return Comp.Image.fromURL(
                            f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640"
                        )
        return None

    async def _read_image(self, event: AstrMessageEvent, image: Comp.Image) -> bytes:
        source = image.url or image.file or image.path or ""
        if (
            source.startswith(("https://", "http://", "base64://", "file:"))
            or Path(source).is_absolute()
        ):
            return await self.reader.read(source)
        if event.get_platform_name() == "aiocqhttp" and image.file:
            try:
                reply = await asyncio.wait_for(
                    event.bot.call_action("get_image", file=image.file), 10
                )
                info = reply.get("data", reply)
                # NapCat may run on another host, so use its URL rather than its path.
                if info.get("url"):
                    return await self.reader.read(info["url"])
            except MediaInputError:
                raise
            except Exception as exc:
                logger.debug(
                    "[pictools] Could not resolve image: %s", type(exc).__name__
                )
        raise MediaInputError("没有可用的图片地址，请重新发送原图。")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10)
    async def handle_message(self, event: AstrMessageEvent):
        """Handle image commands, help and a user's pending image upload."""
        if self.closed or not self._allowed(event):
            return
        key, now = self._key(event), time.monotonic()
        self._prune(now)
        try:
            operation = parse_command(
                self._text(event), self.config.get("match_mode", True)
            )
        except ValueError as exc:
            event.stop_event()
            yield event.plain_result(str(exc))
            return
        if operation and operation.name == "帮助":
            event.stop_event()
            help_text = HELP
            if not self.config.get("match_mode", True):
                help_text += "\n当前普通命令需加 / 前缀，emoji+emoji 仍可直接触发。"
            yield event.plain_result(help_text)
            return
        if operation and operation.name == "取消":
            event.stop_event()
            action = self.pending.pop(key, None)
            yield event.plain_result(
                "已取消图片处理。" if action else "当前没有等待处理的图片。"
            )
            return
        if operation is None:
            action = self.pending.get(key)
            if action is None:
                return
            # A pending operation consumes only an image upload, never unrelated text.
            if self._text(event).startswith("/"):
                return
            image = self._first_image(event.get_messages())
            if image is None:
                for part in event.get_messages():
                    if isinstance(part, Comp.Reply):
                        image = self._first_image(part.chain or [])
                        if image is not None:
                            break
            if image is None:
                return
            operation = action.operation
        else:
            image = None
        event.stop_event()
        if key in self.in_flight:
            yield event.plain_result("你的上一张图片仍在处理中，请稍候。")
            return
        if self.active >= self._integer("max_concurrent", 2, 1):
            yield event.plain_result("图片处理繁忙，请稍后重试。")
            return
        cooldown = self._integer("cooldown_seconds", 3, 0)
        if now - self.last_request.get(key, -float("inf")) < cooldown:
            yield event.plain_result(f"操作太快，请间隔 {cooldown} 秒后重试。")
            return
        # Reserve capacity before any network request or worker is started.
        self.active += 1
        self.in_flight.add(key)
        try:
            if operation.name in {"喜报", "悲报"}:
                self.last_request[key] = now
                self.last_request.move_to_end(key)
                worker = asyncio.create_task(
                    asyncio.to_thread(
                        generate_report,
                        operation.name,
                        operation.text,
                        self._integer("report_font_size", 65, 24),
                        self.limits,
                    )
                )
            elif operation.name == "emoji合成":
                self.last_request[key] = now
                self.last_request.move_to_end(key)
                left, right = operation.text.split(" ", 1)
                url = await asyncio.to_thread(emoji_kitchen_url, left, right)
                try:
                    data = await self.reader.read(url)
                except MediaInputError as exc:
                    raise MediaInputError(
                        "合成表情下载失败，请稍后重试；"
                        "此功能需要能访问 www.gstatic.com。"
                    ) from exc
                worker = asyncio.create_task(
                    asyncio.to_thread(
                        process_image, data, Operation("原图"), self.limits
                    )
                )
            elif operation.name in {"杀", "操你", "抽你"}:
                if event.get_platform_name() != "aiocqhttp":
                    raise MediaInputError(
                        "此表情包需要 QQ 头像，仅支持 NapCat / OneBot v11。"
                    )
                if not self.config.get("enable_at_avatar", True):
                    raise MediaInputError("头像功能已关闭，请在插件配置中开启后重试。")
                target_qq = next(
                    (
                        str(part.qq)
                        for part in event.get_messages()
                        if isinstance(part, Comp.At)
                        and str(part.qq).isascii()
                        and str(part.qq).isdigit()
                        and str(part.qq) != str(event.get_self_id())
                    ),
                    None,
                )
                if target_qq is None:
                    raise MediaInputError(
                        f"用法：{operation.name} @目标用户（@机器人只用于唤醒）。"
                    )
                self.last_request[key] = now
                self.last_request.move_to_end(key)
                target_url = f"https://q1.qlogo.cn/g?b=qq&nk={target_qq}&s=640"
                commander_data = None
                if operation.name in {"操你", "抽你"}:
                    sender_qq = str(event.get_sender_id())
                    if not sender_qq.isascii() or not sender_qq.isdigit():
                        raise MediaInputError("无法获取发送者的 QQ 头像。")
                    sender_url = f"https://q1.qlogo.cn/g?b=qq&nk={sender_qq}&s=640"
                    data = await self.reader.read(target_url)
                    commander_data = await self.reader.read(sender_url)
                else:
                    data = await self.reader.read(target_url)
                worker = asyncio.create_task(
                    asyncio.to_thread(
                        generate_meme, operation.name, data, commander_data, self.limits
                    )
                )
            else:
                if image is None:
                    image = await self._find_image(event)
                if image is None:
                    if len(self.pending) >= 1024 and key not in self.pending:
                        yield event.plain_result(
                            "等待图片的请求较多，请将命令和图片一起发送。"
                        )
                        return
                    timeout = self._integer("pending_timeout", 120, 1)
                    self.pending[key] = PendingAction(operation, now + timeout)
                    yield event.plain_result(
                        f"已选择「{operation.name}」，请在 {timeout} 秒内发送图片；"
                        "发送「取消图片处理」可退出。"
                    )
                    return
                self.pending.pop(key, None)
                self.last_request[key] = now
                self.last_request.move_to_end(key)
                data = await self._read_image(event, image)
                if operation.name in MEME_SPECS:
                    worker = asyncio.create_task(
                        asyncio.to_thread(
                            generate_meme, operation.name, data, limits=self.limits
                        )
                    )
                else:
                    worker = asyncio.create_task(
                        asyncio.to_thread(process_image, data, operation, self.limits)
                    )
            self.workers.add(worker)
            try:
                # Do not abandon a running Pillow thread on cancellation or timeout.
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    await worker
                except Exception:
                    pass
                raise
            finally:
                self.workers.discard(worker)
            output_image = Comp.Image.fromBytes(result.data)
            if (
                operation.name == "emoji合成"
                and event.get_platform_name() == "aiocqhttp"
            ):
                # The AstrBot image serializer drops NapCat's sticker fields.
                message = [
                    {
                        "type": "image",
                        "data": {
                            "file": output_image.file,
                            "sub_type": 1,
                            "summary": "[合成表情]",
                        },
                    }
                ]
                if result.note:
                    message.insert(0, {"type": "text", "data": {"text": result.note}})
                group_id = event.get_group_id()
                target = (
                    {"group_id": int(group_id)}
                    if group_id
                    else {"user_id": int(event.get_sender_id())}
                )
                await event.bot.call_action(
                    "send_group_msg" if group_id else "send_private_msg",
                    message=message,
                    self_id=event.get_self_id(),
                    **target,
                )
                return
            chain = [output_image]
            if result.note:
                chain.insert(0, Comp.Plain(result.note + "\n"))
            yield event.chain_result(chain)
        except (MediaInputError, ImageProcessingError) as exc:
            yield event.plain_result(str(exc))
        except Exception:
            logger.exception("[pictools] Image processing failed")
            yield event.plain_result("图片处理失败，请换一张图片重试。")
        finally:
            self.active -= 1
            self.in_flight.discard(key)

    async def terminate(self):
        self.closed = True
        self.pending.clear()
        await self.reader.close()
        if self.workers:
            await asyncio.gather(*tuple(self.workers), return_exceptions=True)
