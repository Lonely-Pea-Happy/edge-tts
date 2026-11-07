"""界面文案集中管理（中文 / 英文）。

状态栏提示、播放器提示、异常翻译都收在这里：要改文案只改这个文件，不用再翻
main_window.py / tts_engine.py / player.py。

约定：
- 不带变量的用常量（大写命名）；切语言时这些常量会被 `_apply_lang()` 就地改写，
  调用处一律写 `messages.READY` 这种属性访问（不要 `from messages import READY`），
  这样切语言后自动取到新语言的值；
- 带变量的用小函数，函数体里用 `_s(中文, English)` / `_f(格式串…)` 取当前语言。
"""

from __future__ import annotations

import asyncio

import i18n


def _s(zh: str, en: str) -> str:
    return i18n.pick((zh, en))


def _f(zh: str, en: str, **kw) -> str:
    return i18n.pick((zh, en)).format(**kw)


# ---------------------------------------------------------------- 常量表
# 切语言时就地改写模块里的同名常量。

_CONST = {
    "READY": ("准备就绪", "Ready"),
    "EDGE_MISSING": (
        "未检测到 edge-tts，请先执行 pip install edge-tts",
        "edge-tts is not installed. Run: pip install edge-tts",
    ),
    "EDGE_MISSING_JOB": (
        "未安装 edge-tts：请执行 pip install edge-tts",
        "edge-tts is not installed: run pip install edge-tts",
    ),
    "NEED_TEXT": ("请先输入要合成的文本", "Enter some text first"),
    "NO_VOICE": (
        "当前语言下没有可用发音人，请换一个语言",
        "No voice available for this language; pick another language",
    ),
    "SYNTHESIZING": ("正在合成…", "Synthesizing…"),
    "CANCELING": ("正在取消…", "Canceling…"),
    "PREVIEW_DONE": ("试听中", "Playing preview"),
    "QUEUE_BUSY_SAVE_AS": (
        "队列生成中，暂时不能另存为",
        "Can't use Save as while the queue is running",
    ),
    "TEXT_CLEARED": ("文本已清空", "Text cleared"),
    "CLEAR_EMPTY": ("文本区里还没有内容", "The text area is empty"),
    "QUEUE_CLEAR_EMPTY": ("队列里还没有分段", "The queue is empty"),
    "SUB_ON": (
        "生成时将同时导出同名 .srt 字幕",
        "A matching .srt subtitle will be exported with the audio",
    ),
    "SUB_OFF": ("已关闭字幕导出", "Subtitle export is off"),
    "OUTPUT_DIR_BAD": ("输出目录不可用，请重新选择", "Output folder isn't usable; choose another"),
    "OUTPUT_OPEN_FAILED": ("无法打开输出目录", "Couldn't open the output folder"),
    "QUEUE_EMPTY": (
        "没有可拆分的文本，请先输入内容",
        "Nothing to split into a queue; enter some text first",
    ),
    "IMPORT_UNSUPPORTED": (
        "只支持导入 txt / srt / md 文本文件；音频请用「生成语音」产出",
        "Only txt / srt / md files can be imported; use Generate to make audio",
    ),
    "IMPORT_EMPTY": ("这个文件里没有可朗读的文字", "This file has no readable text"),
    "IMPORT_READ_FAILED": (
        "读不了这个文件，可能没有权限或被其它程序占用",
        "Couldn't read this file (no permission, or it's being used by another program)",
    ),
    "PLAYER_NO_FILE": ("音频文件不存在", "The audio file doesn't exist"),
    "ERR_FILE_LOCKED": (
        "写入失败：目标文件正被占用。多半是它还在播放器里开着，停止播放后再生成一次；"
        "如果仍失败，请关掉打开该文件的其它程序。",
        "Write failed: the target file is in use. It's usually still open in the player — "
        "stop playback and generate again. If it still fails, close other programs using it.",
    ),
    "ERR_DISK_FULL": (
        "磁盘空间不足，无法写入音频。清理磁盘或换一个输出目录。",
        "Not enough disk space to write the audio. Free up space or choose another output folder.",
    ),
    "ERR_BAD_PATH": (
        "保存路径不合法（过长或含非法字符），请换一个更短的输出目录或文件名。",
        "The save path is invalid (too long or contains illegal characters). "
        "Use a shorter folder or file name.",
    ),
    "ERR_TIMEOUT": (
        "请求超时：网络到微软语音服务太慢，建议检查代理或稍后重试。",
        "Request timed out: the connection to the Microsoft speech service is too slow. "
        "Check your proxy or try again later.",
    ),
    "ERR_NO_AUDIO": (
        "服务没有返回音频数据，请检查网络后重试。",
        "The service returned no audio data. Check your network and try again.",
    ),
    "ERR_NETWORK": (
        "无法连接微软语音服务，请检查网络或代理设置。",
        "Can't connect to the Microsoft speech service. Check your network or proxy settings.",
    ),
    "ERR_AUTH": (
        "语音服务拒绝了请求（鉴权失败），请更新 edge-tts 版本后重试。",
        "The speech service rejected the request (authentication failed). "
        "Update edge-tts and try again.",
    ),
    "ERR_DNS": (
        "域名解析失败，请检查网络连接或 DNS 设置。",
        "Domain name resolution failed. Check your connection or DNS settings.",
    ),
}


def _apply_lang() -> None:
    g = globals()
    for name, pair in _CONST.items():
        g[name] = i18n.pick(pair)


i18n.on_change(_apply_lang)
_apply_lang()


# ---------------------------------------------------------------- 启动与语音库


def voices_updated(count: int) -> str:
    return _f("语音库已更新，共 {n} 个发音人", "Voice list updated · {n} voices", n=count)


def voices_stale(reason: str) -> str:
    return _f(
        "语音库更新失败，正在使用本地缓存（{r}）",
        "Couldn't refresh the voice list; using the local cache ({r})",
        r=reason,
    )


# ---------------------------------------------------------------- 发音人列表


def locale_all(total: int) -> str:
    """语言下拉里的「全部语言」。"""
    return _f("全部语言 · {n}", "All languages · {n}", n=total)


def all_voices(total: int) -> str:
    return _f("全部语言 · 共 {n} 个发音人", "All languages · {n} voices", n=total)


# ---------------------------------------------------------------- AI 扩写


def ai_need_sentence() -> str:
    return _f(
        "先写一句要扩写的话（一句就够，AI 会补细节）",
        "Type one line to expand first (one sentence is enough)",
    )


def ai_generating(chars: int) -> str:
    return _f(
        "AI 正在扩写，目标约 {n} 字…",
        "Writing with AI, target ~{n} chars…",
        n=chars,
    )


def ai_done(chars: int) -> str:
    return _f(
        "AI 写好了 {n} 字，确认后替换或追加进正文",
        "AI wrote {n} characters; replace or append it after reviewing",
        n=chars,
    )


def ai_ollama_ok(names: list[str]) -> str:
    """检测连上了本机 Ollama，并把可用模型名回显出来。"""
    if not names:
        return _f(
            "连上本机 Ollama，但还没有模型：先 ollama pull 一个（建议 3B/4B）",
            "Ollama is running but has no models yet: `ollama pull` one (3B/4B recommended)",
        )
    listing = "、".join(names[:4]) + ("…" if len(names) > 4 else "")
    return _f(
        "已连上本机 Ollama，可用模型：{names}",
        "Ollama connected; available models: {names}",
        names=listing,
    )


def ai_ollama_model_picked(name: str) -> str:
    return _f("已填上本机模型「{name}」", "Local model set to “{name}”", name=name)


def ollama_downloading(done: int, total: int) -> str:
    """下载安装包时的进度文案：有总长就给百分比，没有就只报已下多少。"""
    mb = done / (1024 * 1024)
    if total > 0:
        pct = min(100, int(done * 100 / total))
        return _f(
            "正在下载 Ollama 安装包… {pct}%（{mb:.1f} / {all:.1f} MB）",
            "Downloading Ollama installer… {pct}% ({mb:.1f} / {all:.1f} MB)",
            pct=pct, mb=mb, all=total / (1024 * 1024),
        )
    return _f(
        "正在下载 Ollama 安装包… 已下 {mb:.1f} MB",
        "Downloading Ollama installer… {mb:.1f} MB so far",
        mb=mb,
    )


def ollama_installer_opened() -> str:
    return _f(
        "安装向导已打开：按提示装完，回到这里点「检测连接」",
        "The installer is open: finish it, then click “Test connection” here",
    )


def ollama_launch_failed(path: str) -> str:
    return _f(
        "安装包已下好（{path}），但没能自动打开：双击它手动安装",
        "Installer downloaded ({path}) but could not be opened: run it manually",
        path=path,
    )


def ai_inserted(chars: int, replaced: bool) -> str:
    return _f(
        "已{how}正文 · {n} 字",
        "{how} the text · {n} chars",
        how=_f("替换", "Replaced"),
        n=chars,
    )


# ---------------------------------------------------------------- 合成 / 试听 / 保存


def preview_progress(pct: int) -> str:
    return _f("正在生成试听音频 {pct}%", "Generating preview {pct}%", pct=pct)


def preview_done_limited(chars: int) -> str:
    """试听只读了前面一段，明确告诉用户后面没读。"""
    return _f(
        "试听中 · 只朗读了前 {n} 字，完整内容请点“生成语音”",
        "Playing preview · only the first {n} characters; use Generate for the full text",
        n=chars,
    )


def locale_voices(label: str, count: int, total: int) -> str:
    """换语言时说明这一档有多少发音人，避免“语音库 322 个但只看到 6 个”的困惑。"""
    return _f(
        "{l} · {n} 个发音人（语音库共 {t} 个）",
        "{l} · {n} voices (library total {t})",
        l=label, n=count, t=total,
    )


def voice_combo_hint(count: int, total: int) -> str:
    return _f(
        "当前语言共 {n} 个发音人，语音库合计 {t} 个（换语言可切换）",
        "{n} voices in this language, {t} in the library (switch language to change)",
        n=count, t=total,
    )


def locale_item(label: str, count: int) -> str:
    """语言下拉里的条目：带上该语言的发音人数。"""
    return _f("{l} · {n}", "{l} · {n}", l=label, n=count)


def synth_progress(pct: int, chars: int) -> str:
    return _f("正在合成 {pct}%（约 {n} 字）", "Synthesizing {pct}% (~{n} chars)", pct=pct, n=chars)


def saved(name: str) -> str:
    return _f("已保存 · {name}", "Saved · {name}", name=name)


def saved_with_srt(name: str, srt_name: str) -> str:
    return _f(
        "已保存 · {name}，字幕 {srt}",
        "Saved · {name}, subtitles {srt}",
        name=name, srt=srt_name,
    )


# ---------------------------------------------------------------- 批量队列


def queue_split(segments: int, total: int) -> str:
    return _f("已拆分为 {n} 段，队列共 {t} 段", "Split into {n} items; the queue now has {t}", n=segments, t=total)


def queue_removed(index: int, left: int) -> str:
    """index 为用户看到的序号（从 1 开始）。"""
    return _f("已移除第 {i} 段，队列剩 {n} 段", "Removed item {i}; {n} left in the queue", i=index, n=left)


def queue_cleared(count: int) -> str:
    return _f("已清空队列（{n} 段）", "Queue cleared ({n} items)", n=count)


def queue_started(total: int) -> str:
    return _f("开始生成队列，共 {n} 段", "Generating the queue · {n} items", n=total)


def queue_progress(index: int, total: int, pct: int) -> str:
    """index 为当前段号（从 1 开始）。"""
    return _f(
        "正在生成第 {i}/{n} 段 · {pct}%",
        "Generating item {i}/{n} · {pct}%",
        i=index, n=total, pct=pct,
    )


def queue_canceled(done: int, total: int) -> str:
    return _f("已取消 · 完成 {d}/{n} 段", "Canceled · {d}/{n} done", d=done, n=total)


def queue_playing(index: int) -> str:
    """index 为用户看到的段号（从 1 开始）。"""
    return _f("正在播放第 {i} 段", "Playing item {i}", i=index)


def queue_play_missing(index: int) -> str:
    return _f(
        "第 {i} 段还没有生成好的音频，先点「生成队列」",
        "Item {i} has no audio yet — run Generate queue first",
        i=index,
    )


def queue_done(done: int, elapsed_sec: float) -> str:
    return _f(
        "队列完成 · 成功 {d} 段 · 用时 {sec:.0f} 秒",
        "Queue finished · {d} succeeded · {sec:.0f}s",
        d=done, sec=elapsed_sec,
    )


def queue_done_with_failures(
    done: int, failed: int, first_index: int, first_error: str, elapsed_sec: float
) -> str:
    """first_index 为第一段失败项的用户序号（从 1 开始）。"""
    return _f(
        "队列完成 · 成功 {d}，失败 {f}（第 {i} 段：{err}） · 用时 {sec:.0f} 秒",
        "Queue finished · {d} succeeded, {f} failed (item {i}: {err}) · {sec:.0f}s",
        d=done, f=failed, i=first_index, err=first_error, sec=elapsed_sec,
    )


# ---------------------------------------------------------------- 导入文本


def imported(name: str, chars: int) -> str:
    return _f("已导入 {name} · {n} 字", "Imported {name} · {n} chars", name=name, n=chars)


def imported_appended(name: str, chars: int) -> str:
    """编辑区原有内容会保留，追加在末尾——避免一次误拖把写好的稿子冲掉。"""
    return _f(
        "已追加导入 {name} · {n} 字（原有内容已保留）",
        "Appended {name} · {n} chars (existing text kept)",
        name=name, n=chars,
    )


def imported_ignored(name: str, chars: int, ignored: int) -> str:
    """一次拖了多个文件时只取第一个，其余的在同一条提示里交代清楚。"""
    return _f(
        "已导入 {name} · {n} 字 · 另有 {k} 个文件被忽略（一次只导入一个）",
        "Imported {name} · {n} chars · {k} more file(s) ignored (one at a time)",
        name=name, n=chars, k=ignored,
    )


def import_failed(reason: str) -> str:
    return {
        "unsupported": IMPORT_UNSUPPORTED,
        "empty": IMPORT_EMPTY,
        "read": IMPORT_READ_FAILED,
    }.get(reason, IMPORT_READ_FAILED)


# ---------------------------------------------------------------- 主题 / 播放器


def theme_switched(label: str) -> str:
    return _f("主题：{l}", "Theme: {l}", l=label)


def player_no_file() -> str:
    return PLAYER_NO_FILE


def player_open_failed(detail: str) -> str:
    return _f("无法打开音频：{d}", "Couldn't open the audio: {d}", d=detail)


def player_play_failed(detail: str) -> str:
    return _f("播放失败：{d}", "Playback failed: {d}", d=detail)


def player_hint(msg: str) -> str:
    """播放器出错时补一句兜底办法，提示用户还能用系统播放器打开。"""
    return _s(msg + "，可用系统播放器打开", msg + " — you can open it in the system player")


# ---------------------------------------------------------------- 异常 → 用户话术


def friendly_error(exc: BaseException) -> str:
    """把常见异常翻译成用户看得懂、且知道下一步做什么的话。"""
    text = str(exc) or exc.__class__.__name__
    low = text.lower()
    if (
        isinstance(exc, PermissionError)
        or "winerror 5" in low
        or "拒绝访问" in text
        or "permission denied" in low
        or "errno 13" in low
    ):
        return ERR_FILE_LOCKED
    if (
        "winerror 112" in low
        or "errno 28" in low
        or "no space" in low
        or "空间不足" in text
        or "磁盘已满" in text
    ):
        return ERR_DISK_FULL
    if (
        "winerror 3" in low
        or "winerror 123" in low
        or "path too long" in low
        or "文件名" in text
        or "invalid name" in low
    ):
        return ERR_BAD_PATH
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in low:
        return ERR_TIMEOUT
    if "noaudioreceived" in low or "no audio" in low:
        return ERR_NO_AUDIO
    if any(
        k in low
        for k in ("cannot connect", "connector", "network", "ssl", "proxy", "getaddrinfo", "timed out")
    ):
        return ERR_NETWORK
    if "403" in low or "401" in low:
        return ERR_AUTH
    if "name or service not known" in low or "temporary failure in name resolution" in low:
        return ERR_DNS
    return text
