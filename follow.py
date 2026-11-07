"""朗读跟随：把「一句的起始/结束时间」映射回正文里的字符区间。

合成时 edge-tts 会逐句回传 SentenceBoundary（offset/duration，单位 100ns），
SynthJob 顺手攒成了时间轴，字幕也用这批数据。播放时拿这份时间轴就能判断
「现在读到第几句」，剩下的问题只有一步：那句话在正文里的位置。

难点不在「有没有文本」，而在对位：

1. 字幕那边会规范化空白（连续空格压成一个）、把超长句折成两行，原文里的换行
   和全角空格都可能不一样，直接 `find` 会落空；
2. 正文里常有重复句（"谢谢大家。"出现两次），从头 find 会全落到第一句；
3. 边界事件的 `text` 实测是整句，但也不能假定它一定与正文逐字相同。

所以主路径是「按句末标点/换行把正文切句，分句数与时间轴条数一致就 1:1 对位」——
条数一致意味着顺序天然对齐，重复句也不会错位；只有条数对不上时才退回
「顺序找前缀，再扩到它所在的整句」。
纯逻辑，不依赖 Qt。
"""

from __future__ import annotations

import re

_END_PUNCT = set("。．.！？!?…；;")


def _is_decimal_point(text: str, i: int) -> bool:
    """英文句点既当句末也当小数点：`1.5`、`v1.2`、`...` 里的点不算断句。"""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    return nxt.isdigit() or nxt == "." or nxt == "\u2026"
_CLOSERS = set("”’\"'）)】]」』")


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """规范化正文，并给出每个规范化字符对应的原文下标。

    规则与字幕那边一致：空白（含全角空格、`\\u200b`）连续段压成一个半角空格，
    首尾空白丢掉。合成出来的空格映射到它所在那段空白的第一个字符。
    """
    out: list[str] = []
    idxs: list[int] = []
    space_at: int | None = None
    for i, ch in enumerate(text):
        if ch.isspace() or ch == "\u200b":
            if out and space_at is None:
                space_at = i
            continue
        if space_at is not None:
            out.append(" ")
            idxs.append(space_at)
            space_at = None
        out.append(ch)
        idxs.append(i)
    return "".join(out), idxs


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """按句末标点和换行把正文切句，返回每句的 [start, end)。"""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if start is None:
            if ch.isspace():
                i += 1
                continue
            start = i
        if ch in _END_PUNCT:
            if ch in ".．" and _is_decimal_point(text, i):
                i += 1
                continue
            j = i + 1
            while j < n and (text[j] in _END_PUNCT or text[j] in _CLOSERS):
                j += 1
            spans.append((start, j))
            start = None
            i = j
            continue
        if ch == "\n":
            if start is not None and text[start:i].strip():
                spans.append((start, i))
            start = None
            i += 1
            continue
        i += 1
    if start is not None and text[start:].strip():
        spans.append((start, n))

    out: list[tuple[int, int]] = []
    for a, b in spans:
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def _cue_pattern(text: str) -> str:
    """把边界事件的文字变成正则：空白按「可有可无的单个空格」匹配。

    字幕那边会把超长句在标点处折成两行（插入的 `\\n` 在原文里根本不存在），
    而正文里的换行在规范化后是空格。两头都对齐不了，所以干脆让空白宽松匹配。
    """
    parts = [re.escape(p) for p in re.split(r"[ \t\r\n\u200b\u00a0\u3000]+", text) if p]
    if not parts:
        return ""
    return r"[ ]?".join(parts)


def _matches_at(sentence: str, cue_text: str) -> bool:
    pattern = _cue_pattern(cue_text)
    if not pattern:
        return False
    return re.match(pattern, normalize(sentence)) is not None


def _sentence_of(spans: list[tuple[int, int]], pos: int) -> tuple[int, int] | None:
    for a, b in spans:
        if a <= pos < b:
            return (a, b)
    return None


def cue_ranges(
    source: str, cues: list[tuple[float, float, str]]
) -> list[tuple[int, int] | None]:
    """把每条时间轴映射到正文区间，映射不上的那条给 None。

    优先「分句数 == 时间轴条数」的 1:1 对位（边界事件每句一条，正常都成立，
    顺序天然对齐，重复句也不会错位）；对不上时退回顺序匹配，并把命中位置扩到
    它所在的整句，避免只高亮到句首那一小段。
    """
    spans = sentence_spans(source)
    if not cues:
        return []

    if spans and len(spans) == len(cues):
        hits = sum(1 for span, cue in zip(spans, cues) if _matches_at(source[span[0]:span[1]], cue[2]))
        if hits >= max(1, int(len(cues) * 0.7)):
            return [tuple(span) for span in spans]

    norm, idxs = normalize_with_map(source)
    out: list[tuple[int, int] | None] = []
    cursor = 0
    for _start, _end, text in cues:
        pattern = _cue_pattern(str(text))
        if not pattern:
            out.append(None)
            continue
        match = re.compile(pattern).search(norm, cursor)
        if match is None:
            out.append(None)
            continue
        first = idxs[match.start()]
        cursor = match.end()
        span = _sentence_of(spans, first)
        if span is not None:
            out.append(span)
            continue
        last = idxs[match.end() - 1] + 1
        out.append((first, last))
    return out


def cue_index_at(
    cues: list[tuple[float, float, str]],
    seconds: float,
    tail_grace: float = 1.0,
    head_grace: float = 1.0,
) -> int | None:
    """某个时刻正在朗读第几句（从 0 起），不在任何一句里就给 None。

    句子之间常有几毫秒空隙，空隙里沿用上一句，避免高亮闪一下又灭；
    音频开头常有几十毫秒静音，所以 head_grace 内也算第一句（一载入就亮）。
    离最后一句结束超过 tail_grace 秒（例如音频尾部有静音、或用户往后跳）
    就当作「读完了」，返回 None。
    """
    if not cues or seconds < 0:
        return None
    if seconds < cues[0][0]:
        return 0 if cues[0][0] - seconds <= head_grace else None
    idx: int | None = None
    for i, (start, _end, _text) in enumerate(cues):
        if start <= seconds:
            idx = i
        else:
            break
    if idx is None:
        return None
    if seconds > cues[idx][1] + tail_grace:
        return None
    return idx
