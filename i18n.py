"""界面语言。

中文是默认语言，英文是第二语言。这里只放两样东西：
1. 当前语言状态（含持久化值），以及切语言时的通知；
2. 主窗口 / 控件用的界面文案表（成对的 zh / en）。

`messages.py` 里那些带变量的提示语不进这张表（它们本身就成对写在 messages 里），
避免同一句文案在两个文件里各存一遍。
"""

from __future__ import annotations

LANG_CODES = ("zh", "en")
LANG_LABELS = {"zh": "中文（简体）", "en": "English"}
DEFAULT = "zh"

_current = DEFAULT
_listeners: list = []


def lang() -> str:
    return _current


def set_lang(code: str, *, notify: bool = True) -> None:
    """切换界面语言；同一个语言重复设置不触发重排。"""
    global _current
    if code not in LANG_CODES:
        code = DEFAULT
    if code == _current:
        return
    _current = code
    if notify:
        for fn in list(_listeners):
            fn()


def on_change(fn) -> None:
    """注册「语言变了要重排界面」的回调。"""
    if fn not in _listeners:
        _listeners.append(fn)


def pick(pair: tuple[str, str]) -> str:
    """取一对 (中文, 英文) 里当前语言的那一条。"""
    return pair[0] if _current == "zh" else pair[1]


def t(key: str, **kw) -> str:
    pair = _T.get(key)
    if pair is None:
        return key
    text = pick(pair)
    return text.format(**kw) if kw else text


# ---------------------------------------------------------------- 界面文案
# 键名按区域分组；带 {placeholder} 的用 t(key, x=...) 调用。

_T: dict[str, tuple[str, str]] = {
    # 标题栏
    "bar.theme": ("切换主题", "Switch theme"),
    "bar.theme_state": ("主题：{name}（点击切换）", "Theme: {name} (click to switch)"),
    "bar.lang": ("界面语言", "Display language"),
    "bar.lang_state": ("界面语言：{name}（点击切换）", "Language: {name} (click to switch)"),
    "bar.min": ("最小化", "Minimize"),
    "bar.max": ("最大化", "Maximize"),
    "bar.restore": ("还原", "Restore"),
    "bar.close": ("关闭", "Close"),

    # 主题档位
    "theme.system": ("跟随系统", "System"),
    "theme.light": ("浅色", "Light"),
    "theme.dark": ("深色", "Dark"),

    # 页头
    "page.title": ("文字转语音", "Text to Speech"),
    "page.subtitle": (
        "基于微软 Edge 神经语音（edge-tts），支持 100+ 语言与发音人",
        "Neural voices from Microsoft Edge (edge-tts) · 100+ languages and voices",
    ),

    # 文本卡片
    "editor.title": ("文本内容", "Text"),
    "editor.placeholder": ("在这里输入或粘贴要合成的文字……", "Type or paste the text to synthesize…"),
    "editor.clear": ("清空", "Clear"),
    "editor.clear_tip": ("清空文本区（会先让你确认一次）", "Clear the text area (asks for confirmation)"),
    "editor.queue": ("按行拆分入队", "Split into queue"),
    "editor.queue_tip": (
        "每个非空行作为一段，超长行会按句号继续切分",
        "One item per non-empty line; long lines split at sentence ends",
    ),
    "editor.hint": (
        "中英混排、标点停顿由语音引擎自动处理",
        "Mixed languages and punctuation pauses are handled by the engine",
    ),
    "editor.count_zero": ("0 字", "0 chars"),
    "editor.count": ("{n} 字 · 约 {sec} 秒", "{n} chars · ~{sec}s"),

    # 队列
    "queue.title": ("队列", "Queue"),
    "queue.clear": ("清空队列", "Clear queue"),
    "queue.head": (
        "队列 · {n} 段 · {chars} 字 · 约 {span}",
        "Queue · {n} items · {chars} chars · ~{span}",
    ),
    "queue.waiting": ("等待", "Waiting"),
    "queue.running": ("生成中", "Generating"),
    "queue.done": ("已完成", "Done"),
    "queue.failed": ("失败", "Failed"),
    "queue.play_tip": ("播放这一段", "Play this item"),
    "queue.pause_tip": ("暂停", "Pause"),
    "queue.remove_tip": ("从队列移除", "Remove from queue"),

    # 时长
    "dur.seconds": ("{n} 秒", "{n}s"),
    "dur.minutes": ("{m} 分 {s:02d} 秒", "{m}m {s:02d}s"),

    # 语音卡片
    "voice.title": ("语音", "Voice"),
    "voice.language": ("语言", "Language"),
    "voice.speaker": ("发音人", "Voice"),
    "voice.preview": ("试听这一句", "Preview this line"),
    "voice.rate": ("语速", "Speed"),
    "voice.pitch": ("音调", "Pitch"),
    "voice.volume": ("音量", "Volume"),
    "voice.output": ("输出目录", "Output folder"),
    "voice.change": ("更改", "Change"),
    "voice.open": ("打开", "Open"),
    "voice.subtitle": ("同时导出字幕 (.srt)", "Also export subtitles (.srt)"),
    "voice.subtitle_tip": (
        "按句切分，时间轴取自语音引擎的句边界事件",
        "Split by sentence; timing comes from the engine's sentence-boundary events",
    ),

    # AI 自动编写（火山方舟 / 豆包）
    "ai.button": ("AI 自动编写", "AI writer"),
    "ai.button_tip": (
        "写一句短话，交给豆包扩成可直接朗读的文案；先看结果，再决定替换还是追加",
        "Turn one short line into a ready-to-read script; review it before inserting",
    ),
    "ai.hint": (
        "写一句要扩写的话，AI 会补成可直接朗读的文案",
        "One line in, a ready-to-read script out",
    ),
    "ai.sentence_ph": ("例如：介绍杭州西湖的清晨", "e.g. Hangzhou's West Lake at dawn"),
    "ai.style": ("风格", "Style"),
    "ai.length": ("长度", "Length"),
    "ai.generate": ("生成文案", "Write"),
    "ai.writing": ("正在写…", "Writing…"),
    "ai.result": ("生成结果（可直接改，再插入正文）", "Result (edit before inserting)"),
    "ai.replace": ("替换正文", "Replace"),
    "ai.append": ("追加到末尾", "Append"),
    "ai.discard": ("丢弃", "Discard"),
    "ai.settings": ("模型设置", "Model settings"),
    "ai.base": ("服务地址", "Base URL"),
    "ai.key": ("API Key", "API key"),
    "ai.model": ("接入点 ID / 模型名", "Endpoint ID / model"),
    "ai.provider": ("服务", "Service"),
    "ai.provider_ark": ("火山方舟 · 豆包", "Ark · Doubao"),
    "ai.provider_ollama": ("本机模型 · Ollama", "Local model · Ollama"),
    "ai.ollama_base": ("本机地址", "Local URL"),
    "ai.ollama_model": ("本机模型名", "Local model"),
    "ai.detect": ("检测连接", "Test connection"),
    "ai.detecting": ("正在检测…", "Testing…"),
    "ai.install": ("一键安装", "Install"),
    "ai.install_cancel": ("取消下载", "Cancel"),
    "ai.page": ("打开下载页", "Download page"),
    "ai.page_tip": (
        "直链下不动就点这里：用浏览器打开官方下载页（浏览器走代理时能下）",
        "If the direct link fails, open the official page in your browser",
    ),
    "ai.install_tip": (
        "没装过 Ollama 就点这里：下载官方安装包，下完会自动打开安装向导",
        "New to Ollama? Download the official installer; it opens automatically when ready",
    ),
    "ai.ollama_hint": (
        "先装 Ollama 并 ollama pull 一个模型（这台机器建议 3B/4B），名字填在这里",
        "Install Ollama and `ollama pull` a model (3B/4B suits this laptop), then use that name",
    ),
    "ai.ollama_need_model": (
        "还没填本机模型：点「检测连接」能列出已装好的模型名",
        "No local model yet: “Test connection” lists the installed ones",
    ),
    "ai.save": ("保存设置", "Save settings"),
    "ai.saved": ("设置已保存", "Settings saved"),
    "ai.fold": ("收起", "Collapse"),

    # 播放条 / 底栏
    "player.play_tip": ("播放 / 暂停（空格；Esc 停止）", "Play / Pause (Space; Esc stops)"),
    "player.external_tip": ("用系统播放器打开", "Open in the system player"),
    "footer.open_dir": ("打开输出目录", "Open output folder"),
    "footer.save_as": ("另存为…", "Save as…"),
    "footer.generate": ("生成语音", "Generate"),
    "footer.generate_tip": ("生成语音（Ctrl+Enter）", "Generate speech (Ctrl+Enter)"),
    "footer.cancel": ("取消生成", "Cancel"),
    "footer.queue_n": ("生成队列 · {n}", "Generate queue · {n}"),

    # 确认卡片
    "confirm.cancel": ("取消", "Cancel"),
    "confirm.clear_title": ("清空全部文本？", "Clear all text?"),
    "confirm.clear_body": (
        "文本区里的内容会被删除，且无法撤销。已生成的音频文件不受影响。",
        "The text will be deleted and cannot be undone. Generated audio files are not affected.",
    ),
    "confirm.clear_ok": ("清空", "Clear"),
    "confirm.queue_title": ("清空队列？", "Clear the queue?"),
    "confirm.queue_body": (
        "队列里的分段会被移除，已生成的文件不受影响。",
        "Queue items will be removed. Generated files are not affected.",
    ),
    "confirm.queue_body_n": (
        "队列里的 {n} 段会被移除，已生成的文件不受影响。",
        "The {n} queue items will be removed. Generated files are not affected.",
    ),
    "confirm.queue_ok": ("清空队列", "Clear queue"),

    # 系统对话框
    "dlg.save_title": ("保存音频", "Save audio"),
    "dlg.mp3_filter": ("MP3 音频 (*.mp3)", "MP3 audio (*.mp3)"),
    "dlg.dir_title": ("选择输出目录", "Choose output folder"),

    # 拖拽提示层
    "drop.main": ("松开鼠标导入 {hint}", "Drop to import {hint}"),
    "drop.more": ("（拖了 {n} 个，只取第一个）", "({n} files, only the first is imported)"),
    "drop.sub": ("内容会追加到文本末尾，原有内容保留", "Content is appended to the end of the text"),

    # 右键菜单
    "menu.undo": ("撤销", "Undo"),
    "menu.redo": ("重做", "Redo"),
    "menu.cut": ("剪切", "Cut"),
    "menu.copy": ("复制", "Copy"),
    "menu.paste": ("粘贴", "Paste"),
    "menu.delete": ("删除", "Delete"),
    "menu.select_all": ("全选", "Select all"),
}
