"""Resolve Emoji Kitchen pairs from a bundled AGPL-3.0 metadata snapshot.

The index is derived from arnav-kr/emoji-kitchen, revision
152b3c690f843879cf28d9dbdee061f69e553fa8. See resources/emoji_kitchen/README.md.
"""

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

from .image_ops import ImageProcessingError

INDEX_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "emoji_kitchen"
    / "index.json.gz"
)


@lru_cache(maxsize=1)
def _emoji_index() -> tuple[dict, dict[str, str]]:
    """Read the compressed index and normalize emoji presentation selectors.

    Returns:
        Combination records and a mapping from normalized to canonical codepoints.

    Raises:
        ImageProcessingError: The installed index is missing or damaged.
    """
    try:
        with gzip.open(INDEX_PATH, "rt", encoding="utf-8") as stream:
            index = json.load(stream)
        normalized = {
            code.replace("-fe0f", "").replace("-fe0e", ""): code
            for code in index["emojis"]
        }
        normalized.update(
            {
                code.replace("-fe0f", "").replace("-fe0e", ""): canonical
                for code, canonical in index["aliases"].items()
            }
        )
        return index["pairs"], normalized
    except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ImageProcessingError(
            "Emoji Kitchen 组合索引无法读取，请重新安装插件恢复素材。"
        ) from exc


def emoji_kitchen_url(left: str, right: str) -> str:
    """Find an existing pair and construct its fixed-host Google image URL.

    Args:
        left: First Unicode emoji, including optional variation selectors.
        right: Second Unicode emoji, including optional variation selectors.

    Returns:
        The indexed PNG URL, with the original asset order preserved.

    Raises:
        ImageProcessingError: Either emoji or their combination is unsupported.
    """
    pairs, normalized = _emoji_index()
    codes = []
    for value in (left, right):
        code = "-".join(
            f"{ord(char):x}" for char in value if char not in "\ufe0e\ufe0f"
        )
        canonical = normalized.get(code)
        if canonical is None:
            raise ImageProcessingError(
                f"当前 Emoji Kitchen 索引暂不支持 {value}，请换一个 emoji。"
            )
        codes.append(canonical)
    pair = pairs.get("|".join(sorted(codes, reverse=True)))
    if pair is None:
        raise ImageProcessingError("这两个 emoji 暂无合成结果，请换一组试试。")
    try:
        date, primary, secondary = pair
        if not re.fullmatch(r"\d{8}", str(date)) or any(
            not re.fullmatch(r"[0-9a-f]+(?:-[0-9a-f]+)*", code)
            for code in (primary, secondary)
        ):
            raise ValueError("Invalid emoji asset record")
        first = "-".join("u" + part for part in primary.split("-"))
        second = "-".join("u" + part for part in secondary.split("-"))
        return f"https://www.gstatic.com/android/keyboard/emojikitchen/{date}/{first}/{first}_{second}.png"
    except (ValueError, TypeError) as exc:
        raise ImageProcessingError(
            "Emoji Kitchen 组合记录异常，请重新安装插件恢复素材。"
        ) from exc
