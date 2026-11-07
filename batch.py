"""批量队列的纯逻辑：拆段、安全文件名、避免覆盖。

放在独立模块是为了能脱离界面单元测试——拆段规则改起来最容易出错。
"""

from __future__ import annotations

import os

MAX_ITEM_CHARS = 300
"""单段字数上限。超过这个长度的行会按句末标点继续切。

对视频剪辑来说一段十几秒最合用，300 字差不多 70 秒，
再长就失去"分段产出"的意义了。
"""

_SENTENCE_END = "。！？!?…"
_TRAILING = "”’\"'）)】]》>"
_BAD_FILENAME = set('\\/:*?"<>|')
_TRAILING_PUNCT = " .。，、；：！？…!?,;:·"


def _split_long_line(line: str, max_chars: int) -> list[str]:
    """把超长的一行按句末标点切成不超过 max_chars 的若干段。"""
    if len(line) <= max_chars:
        return [line]
    out: list[str] = []
    start = 0
    while start < len(line):
        end = min(start + max_chars, len(line))
        if end < len(line):
            cut = -1
            for i in range(end - 1, start, -1):
                if line[i] in _SENTENCE_END:
                    cut = i + 1
                    while cut < len(line) and line[cut] in _TRAILING:
                        cut += 1
                    break
            if cut > start:
                end = cut
        piece = line[start:end].strip()
        if piece:
            out.append(piece)
        start = end
    return out


def truncate_at_sentence(text: str, limit: int = MAX_ITEM_CHARS) -> tuple[str, int]:
    """试听用：超长文本按句末标点截断，绝不从词中间切开。

    返回 (实际要朗读的文本, 截断后的字数)；未截断时第二个值是 0。
    找不到合适的句末标点（或它太靠前，只剩几百字里的一小截）时才硬截。
    """
    text = str(text).strip()
    if len(text) <= limit:
        return text, 0
    head = text[:limit]
    cut = -1
    for i in range(len(head) - 1, limit // 3 - 1, -1):
        if head[i] in _SENTENCE_END or head[i] == "\n":
            cut = i + 1
            while cut < len(head) and head[cut] in _TRAILING:
                cut += 1
            break
    clamped = (head[:cut] if cut > 0 else head).strip()
    return clamped, len(clamped)


def split_segments(text: str, max_chars: int = MAX_ITEM_CHARS) -> list[str]:
    """按行拆段：每个非空行是一段，空行用于分隔不产生空段；
    单行过长时再按句末标点切分。"""
    segments: list[str] = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        segments.extend(_split_long_line(line, max_chars))
    return segments


def safe_stem(text: str, limit: int = 14) -> str:
    """从段落文本里取一个可用作文件名的摘要。"""
    cleaned = "".join(
        " " if (ch in _BAD_FILENAME or ch in "\r\n\t" or ord(ch) < 32) else ch
        for ch in str(text)
    )
    cleaned = " ".join(cleaned.split()).strip(_TRAILING_PUNCT)
    return cleaned[:limit] or "段"


def item_filename(index: int, text: str, ext: str = ".mp3") -> str:
    """队列段的标准文件名：001_摘要.mp3，序号保证在剪辑软件里按名字排序即时间顺序。"""
    return f"{index:03d}_{safe_stem(text)}{ext}"


def unique_path(directory: str, filename: str) -> str:
    """同名文件已存在时追加 (2)(3)…，不覆盖上一次的成果。"""
    target = os.path.join(directory, filename)
    if not os.path.exists(target):
        return target
    stem, ext = os.path.splitext(filename)
    n = 2
    while True:
        candidate = os.path.join(directory, f"{stem}({n}){ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1
