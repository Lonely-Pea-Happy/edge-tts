"""导入外部文本：把 .txt / .srt / .md 读成可以直接合成的纯文本。

拆成独立模块而不是塞进 main_window，是因为「猜编码」「剥字幕时间轴」这类逻辑
出错很隐蔽（读出来是乱码、或者把序号也念了出来），用 GUI 验证太慢——这里可以
用普通断言直接跑。
"""

from __future__ import annotations

import re
from pathlib import Path

# 支持的后缀（小写比较）
SUPPORTED = (".txt", ".srt", ".md")
SUPPORTED_HINT = "txt / srt / md"

# SRT 时间轴行：00:00:01,000 --> 00:00:04,000
# 兼容小数点的写法（部分工具导出成 00:00:01.000）和毫秒位数不同的情况
_TIME_RE = re.compile(
    r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}",
    re.I,
)
_INDEX_RE = re.compile(r"^\s*\d+\s*$")  # 字幕序号（纯数字行）
_TAG_RE = re.compile(r"<[^>]+>")  # <i> / <b> / <font color=...> 这类排版标签
_BRACE_RE = re.compile(r"\{\\[^}]*\}")  # {\an8} 这类 ASS 定位标记

_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}

# Markdown 里会干扰朗读的标记
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_MARKS_RE = re.compile(r"(?:^|\s)(?:[#>*`_~\-]+)(?=\s)")
_MD_INLINE_RE = re.compile(r"[*_`~]+")


class ImportFailed(Exception):
    """导入失败。reason 取值：unsupported / empty / read。

    main_window 按 reason 去 messages 取对应文案，避免把英文异常原样抛给用户。
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


def decode_bytes(raw: bytes) -> str:
    """按常见顺序猜编码：UTF-8（含 BOM）→ GB18030（兼容 GBK/GB2312）。

    中文 txt 很多是记事本存的 GBK；字幕则多半是 UTF-8。猜不出来时用带替换的
    UTF-8 兜底——宁可个别字符变成 ?，也别整段读不出来。
    """
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _needs_space(prev: str, nxt: str) -> bool:
    """英文单词跨行时要补空格；中文行末/行首不补，否则会出现“你 好”。"""
    return prev.isascii() and prev.isalnum() and nxt.isascii() and nxt.isalnum()


def _clean_cue_line(line: str) -> str:
    line = _BRACE_RE.sub("", line)
    line = _TAG_RE.sub("", line)
    for key, value in _ENTITIES.items():
        line = line.replace(key, value)
    return line.strip()


def _join_cue(lines: list[str]) -> str:
    out = ""
    for raw in lines:
        ln = _clean_cue_line(raw)
        if not ln:
            continue
        if out and _needs_space(out[-1], ln[0]):
            out += " "
        out += ln
    return out


def srt_to_text(raw: str) -> str:
    """把 SRT 字幕剥成「每条字幕一行」的纯文本。

    保留逐句换行是为了配合「按行拆分入队」：导入字幕重新配音时，用户通常希望
    一句一段，而不是攒成一大段。
    """
    text = normalize_newlines(raw)
    cues: list[str] = []
    cur: list[str] = []
    for line in text.split("\n"):
        if _TIME_RE.search(line):
            # 出现时间轴 = 一条新字幕开始，先把上一条收尾
            if cur:
                cues.append(_join_cue(cur))
                cur = []
            continue
        if _INDEX_RE.match(line):
            continue
        if not line.strip():
            if cur:
                cues.append(_join_cue(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        cues.append(_join_cue(cur))
    return "\n".join(c for c in cues if c)


def markdown_to_text(raw: str) -> str:
    """去掉 Markdown 标记（标题井号、强调符号、链接地址），只留可朗读的文字。"""
    text = normalize_newlines(raw)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_INLINE_RE.sub("", text)
    text = _MD_MARKS_RE.sub(" ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def text_from_path(path: str | Path) -> tuple[str, str]:
    """读文件并转成纯文本。返回 (纯文本, 小写后缀)。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED:
        raise ImportFailed("unsupported", suffix)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise ImportFailed("read", str(exc)) from exc
    decoded = decode_bytes(raw)
    if suffix == ".srt":
        body = srt_to_text(decoded)
    elif suffix == ".md":
        body = markdown_to_text(decoded)
    else:
        body = normalize_newlines(decoded).strip()
    if not body.strip():
        raise ImportFailed("empty", p.name)
    return body, suffix


def is_supported_name(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED
