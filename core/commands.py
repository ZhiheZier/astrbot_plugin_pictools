"""Command parsing shared by the plugin and its tests."""

import math
import re
from dataclasses import dataclass

import emoji


@dataclass(frozen=True)
class Operation:
    name: str
    value: float | None = None
    text: str = ""


ALIASES = {
    "对称": "左右翻转",
    "镜像": "左右翻转",
    "水平翻转": "左右翻转",
    "垂直翻转": "上下翻转",
    "左对称": "左对称",
    "右对称": "右对称",
    "上对称": "上对称",
    "下对称": "下对称",
    "左右翻转": "左右翻转",
    "上下翻转": "上下翻转",
    "顺时针": "顺时针",
    "逆时针": "逆时针",
    "反色": "反色",
    "灰度": "灰度",
    "黑白": "灰度",
    "倒放": "倒放",
    "调速": "调速",
    "旋转": "旋转",
    "喜报": "喜报",
    "悲报": "悲报",
    "摸头": "摸头",
    "摸头杀": "摸头",
    "发射": "发射",
    "杀": "杀",
    "砍头": "杀",
    "操你": "操你",
    "撅人": "操你",
    "抽你": "抽你",
    "鞭笞": "抽你",
    "图片帮助": "帮助",
    "图片工具": "帮助",
    "对称帮助": "帮助",
    "取消图片处理": "取消",
}

HELP = """图片工具
左对称 / 右对称 / 上对称 / 下对称
对称（左右翻转）/ 上下翻转
顺时针 / 逆时针 / 旋转 角度（顺时针）
反色 / 灰度
倒放（GIF）/ 调速 0.1~10（GIF，2 表示两倍速）
喜报 内容 / 悲报 内容（无需图片，最多 500 字）
摸头 / 发射（图片、引用或 @用户）
杀 @用户 / 操你 @用户 / 抽你 @用户
别名：摸头杀、砍头、撅人、鞭笞
😀+😂（emoji 合成仅支持 表情+表情，可用全角＋）

用法：命令与图片一起发送；引用图片后发送命令；
先发送命令再发送图片；或发送 命令 @用户 处理 QQ 头像。
每次处理第一张图片，优先同条消息，其次引用图片，最后头像。
发送「取消图片处理」退出等待。可加 / 前缀。"""


def parse_command(text: str, match_mode: bool = True) -> Operation | None:
    text = text.strip()
    # Standalone emoji equations trigger independently of command prefixes.
    if len(text) <= 128:
        equation = re.fullmatch(r"([^\s+＋]+)\s*[+＋]\s*([^\s+＋]+)", text)
        if equation:
            left, right = equation.groups()
            if all(
                emoji.is_emoji(value.replace("\ufe0e", "\ufe0f"))
                for value in (left, right)
            ):
                return Operation("emoji合成", text=left + " " + right)
    if text.startswith("/"):
        text = text[1:].strip()
    elif not match_mode:
        return None
    parts = text.split()
    if not parts or parts[0] not in ALIASES:
        return None
    name = ALIASES[parts[0]]
    if name in {"喜报", "悲报"}:
        content = text[len(parts[0]) :].strip()
        if not content:
            raise ValueError(f"用法：{name} 你的内容")
        if len(content) > 500:
            raise ValueError("喜报、悲报内容最多 500 字，请缩短后重试。")
        return Operation(name, text=content)
    if name in {"调速", "旋转"}:
        example = "调速 2" if name == "调速" else "旋转 45"
        if len(parts) != 2:
            raise ValueError(f"用法：{example}")
        try:
            value = float(parts[1])
        except ValueError as exc:
            raise ValueError(f"参数必须是数字，例如：{example}") from exc
        lower, upper = (0.1, 10) if name == "调速" else (-360, 360)
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"{name}参数范围：{lower}~{upper}")
        return Operation(name, value)
    # Ignore ordinary sentences that happen to start with a command word.
    if len(parts) != 1:
        return None
    return Operation(name)
