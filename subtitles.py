"""SRT 字幕生成。

edge-tts 的 SentenceBoundary 事件给出「一句」的 offset/duration（单位 100ns），
但相邻句子的时间区间会重叠几十毫秒，官方 srt_composer 只排序不去重叠，
播放器里会出现两条字幕同时压屏。这里在合成时把结束时间裁到下一句起点，
并把过长的句子折成两行。
"""

from __future__ import annotations

_CUE_BREAKS = set(" 　，,、；;：:！!？?。.）)】]|")


def seconds_to_timestamp(seconds: float) -> str:
    """秒 -> SRT 时间戳 HH:MM:SS,mmm。"""
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000))
    hours, ms_total = divmod(ms_total, 3_600_000)
    minutes, ms_total = divmod(ms_total, 60_000)
    secs, ms = divmod(ms_total, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _char_units(ch: str) -> int:
    """全角字符按 2 个单位计，用于估算显示宽度。"""
    if ord(ch) < 0x2E80:
        return 1
    return 2


def _text_units(text: str) -> int:
    return sum(_char_units(ch) for ch in text)


def wrap_cue_text(text: str, max_units: int = 44) -> str:
    """把一行字幕折成最多两行，优先在标点或空格处断开。"""
    if _text_units(text) <= max_units:
        return text

    half = _text_units(text) / 2.0
    best_pos = None
    best_delta = 1e9
    for i, ch in enumerate(text):
        if i == 0 or i == len(text) - 1:
            continue
        if ch in _CUE_BREAKS:
            delta = abs(_text_units(text[: i + 1]) - half)
            if delta < best_delta:
                best_delta = delta
                best_pos = i + 1

    if best_pos is None:  # 没有合适的标点，按宽度硬切
        acc = 0
        for i, ch in enumerate(text):
            acc += _char_units(ch)
            if acc >= half:
                best_pos = i + 1
                break

    if not best_pos:
        return text
    left = text[:best_pos].strip()
    right = text[best_pos:].strip()
    if not right:
        return left
    return f"{left}\n{right}"


def _normalize(text: str) -> str:
    return " ".join(str(text).replace("\u200b", "").split())


def write_srt(cues: list[tuple[float, float, str]], path: str, *,
              max_units: int = 44) -> str:
    """写 SRT 文件。

    编码用 UTF-8 带 BOM：Windows 上的老播放器（PotPlayer 旧版、部分剪辑软件）
    靠 BOM 判断编码，没有 BOM 中文会乱码。
    换行必须传 newline=""，否则文本模式会把已写好的 CRLF 再翻译一遍，
    落盘变成 "\\r\\r\\n" 的畸形行尾。
    """
    from pathlib import Path

    content = compose_srt(cues, max_units=max_units)
    Path(path).write_text(content, encoding="utf-8-sig", newline="")
    return content


def compose_srt(cues: list[tuple[float, float, str]], *, max_units: int = 44,
                min_duration: float = 0.12) -> str:
    """cues: [(start_sec, end_sec, text)] -> SRT 文本（CRLF 换行）。"""
    ordered = sorted(cues, key=lambda c: c[0])
    rows: list[list] = []
    for start, end, text in ordered:
        cleaned = _normalize(text)
        if not cleaned:
            continue
        s = max(0.0, float(start))
        e = max(s, float(end))
        rows.append([s, e, cleaned])

    # 裁掉与下一句的重叠：字幕不该同时压两条
    for i in range(len(rows) - 1):
        next_start = rows[i + 1][0]
        if rows[i][1] > next_start:
            rows[i][1] = next_start
        if rows[i][1] - rows[i][0] < min_duration:
            rows[i][1] = rows[i][0] + min_duration

    blocks = []
    for index, (start, end, text) in enumerate(rows, 1):
        blocks.append(str(index))
        blocks.append(f"{seconds_to_timestamp(start)} --> {seconds_to_timestamp(end)}")
        blocks.append(wrap_cue_text(text, max_units))
        blocks.append("")
    if not blocks:
        return ""
    return "\n".join(blocks).replace("\n", "\r\n")
