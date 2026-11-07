"""AI 文案扩写：把一句短话交给豆包（火山方舟）扩成可直接朗读的文案。

这里只管两件事：
1. 组请求（提示词、风格、目标字数）与调用接口，纯 Python，不依赖 Qt，方便直接跑断言；
2. 提供 QThread 包装，让界面线程不被网络卡住。

接口走火山方舟的 OpenAI 兼容端点：
    POST {base}/chat/completions
    Authorization: Bearer <API Key>
    {"model": "<推理接入点 ID 或模型名>", "messages": [...], ...}
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

import i18n

# 方舟的默认地域端点；换地域或自建网关时只改 base
DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
# 本机 Ollama 的默认地址（ollama serve 默认监听这个端口）
DEFAULT_OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = ""
TIMEOUT = 60
OLLAMA_TIMEOUT = 120      # 本机小模型慢，给两分钟
PROVIDERS = ("ark", "ollama")

# 官方 Windows 安装包（点了「一键安装」只是下载它，真正的安装向导仍由系统弹出）
INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
INSTALLER_PATH = Path(os.environ.get("TEMP", ".")) / "OllamaSetup.exe"
# 网络连不上直链时，退回浏览器打开这个页面（浏览器可能走代理/VPN，能下）
DOWNLOAD_PAGE = "https://ollama.com/download"

# 风格键 -> (中文名, 英文名, 给模型的风格说明)
STYLES: dict[str, tuple[str, str, str]] = {
    "natural": (
        "自然口播",
        "Natural",
        "像主播或解说那样自然、口语化，短句为主，有一点画面感，不夸张。",
    ),
    "story": (
        "故事感",
        "Story",
        "有场景、有细节、有起伏，像在讲一个小故事，但不要写成小说。",
    ),
    "knowledge": (
        "科普讲解",
        "Explainer",
        "准确、条理清楚，先给结论再解释，适当打比方，不堆术语。",
    ),
    "ad": (
        "宣传文案",
        "Promo",
        "有卖点、有节奏、有记忆点，结尾给一句自然的行动号召。",
    ),
}

# 目标字数档位
LENGTHS: tuple[int, ...] = (100, 200, 300, 500)

_SYSTEM_PROMPT = (
    "你是中文口播文案写手。把用户给的一句话扩写成可以直接朗读的文案。\n"
    "硬性要求：\n"
    "1. 只输出正文，不要标题、不要分点编号、不要 Markdown 标记、不要括号里的说明；\n"
    "2. 用口语化的短句，读出来要顺，避免长定语和书面语；\n"
    "3. 保留原句的意思和语气，不要编造具体数字、人名、机构名；\n"
    "4. 不要出现“大家好”“本期”“以上就是”这类模板开场与收尾。"
)


def style_label(key: str) -> str:
    """当前界面语言下的风格名。"""
    item = STYLES.get(key, STYLES["natural"])
    return item[0] if i18n.lang() == "zh" else item[1]


def length_label(chars: int) -> str:
    return i18n.pick(("约 {n} 字", "~{n} chars")).format(n=chars)


def build_messages(sentence: str, style: str, chars: int) -> list[dict]:
    """组 chat/completions 的 messages。"""
    style_hint = STYLES.get(style, STYLES["natural"])[2]
    user = (
        f"要扩写的一句话：{sentence.strip()}\n"
        f"风格：{style_hint}\n"
        f"目标长度：约 {chars} 个汉字（可以略有出入，别为了凑字数重复啰嗦）。"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def clean_output(text: str) -> str:
    """去掉模型偶尔带出来的包裹符号与多余空行。"""
    text = (text or "").strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    text = text.strip()
    if len(text) >= 2 and text[0] in "“\"「" and text[-1] in "”\"」":
        text = text[1:-1].strip()
    # 连续空行压成一个，段间只留一个空行
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln and (not out or not out[-1]):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _error_text(status: int, body: str) -> str:
    """把 HTTP 状态码翻成人能照着办的话。"""
    detail = ""
    try:
        payload = json.loads(body or "{}")
        detail = str(payload.get("error", {}).get("message", "") or "")
    except Exception:
        detail = (body or "").strip()[:200]
    if status == 401 or status == 403:
        return i18n.pick((
            "API Key 不对或没权限：检查「模型设置」里的 Key 是否完整、是否已开通该模型",
            "API key rejected: check the key in Model settings and that the model is enabled",
        ))
    if status == 404:
        return i18n.pick((
            "接入点不存在：确认「接入点 ID」填的是 ep- 开头的推理接入点（不是模型显示名）",
            "Endpoint not found: make sure the ID starts with ep- (an inference endpoint, not a model name)",
        ))
    if status == 429:
        return i18n.pick((
            "请求太频繁被限流：等十几秒再点一次生成",
            "Rate limited: wait a few seconds and try again",
        ))
    if status >= 500:
        return i18n.pick((
            f"服务端出错（HTTP {status}）：稍后重试；一直失败就换个接入点",
            f"Server error (HTTP {status}): retry later, or use another endpoint",
        ))
    tail = f"：{detail}" if detail else ""
    return i18n.pick((f"请求失败（HTTP {status}）{tail}", f"Request failed (HTTP {status}){tail}"))


def call_ark(
    sentence: str,
    *,
    api_key: str,
    model: str,
    base: str = DEFAULT_BASE,
    style: str = "natural",
    chars: int = 200,
    timeout: int = TIMEOUT,
) -> str:
    """同步调用方舟接口，返回清洗后的文案；失败抛 RuntimeError（文案已翻好）。"""
    if not api_key:
        raise RuntimeError(i18n.pick((
            "还没填 API Key：点「模型设置」填火山方舟的 Key（也可设环境变量 ARK_API_KEY）",
            "No API key yet: open Model settings and paste your Ark key (or set ARK_API_KEY)",
        )))
    if not model:
        raise RuntimeError(i18n.pick((
            "还没填接入点 ID：在火山方舟控制台创建推理接入点后，把 ep- 开头那串填进「模型设置」",
            "No endpoint ID yet: create an inference endpoint in the Ark console and paste the ep-… ID",
        )))
    base = (base or DEFAULT_BASE).rstrip("/")
    url = f"{base}/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": build_messages(sentence, style, chars),
            "temperature": 0.75,
            "max_tokens": max(256, int(chars * 2.2)),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_error_text(exc.code, exc.read().decode("utf-8", "replace"))) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(i18n.pick((
            f"连不上服务：{reason}（检查网络或代理，服务地址默认 {DEFAULT_BASE}）",
            f"Cannot reach the service: {reason} (check network/proxy; default base {DEFAULT_BASE})",
        ))) from exc
    except TimeoutError as exc:
        raise RuntimeError(i18n.pick((
            "等太久了（60 秒没返回）：网络慢或模型排队，稍后再试",
            "Timed out after 60s: slow network or model queue, try again later",
        ))) from exc

    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(i18n.pick((
            "返回内容看不懂（不是预期的 chat/completions 结构），确认服务地址没有被改写",
            "Unexpected response: the base URL may not be an OpenAI-compatible endpoint",
        ))) from exc

    text = clean_output(str(content))
    if not text:
        raise RuntimeError(i18n.pick((
            "模型返回了空内容：换个接入点或把长度调大一点再试",
            "The model returned nothing: try another endpoint or a longer target length",
        )))
    return text


def resolved_key(settings: dict) -> str:
    """环境变量优先于设置里的 Key，方便不把 Key 写进文件。"""
    return (os.environ.get("ARK_API_KEY") or "").strip() or str(settings.get("ai_key", "")).strip()


def provider(settings: dict) -> str:
    """当前用哪条通道；未知值一律当方舟处理。"""
    value = str(settings.get("ai_provider", "ark") or "ark").strip().lower()
    return value if value in PROVIDERS else "ark"


def _ollama_http_error(status: int, body: str) -> str:
    """Ollama 原生接口的错误更像本地服务：404 多半是模型没拉。"""
    detail = ""
    try:
        payload = json.loads(body)
        detail = str(payload.get("error") or payload.get("message") or "").strip()
    except Exception:  # noqa: BLE001
        detail = (body or "").strip()
    detail = detail[:160]
    suffix = f"（{detail}）" if detail else ""
    if status == 404:
        return i18n.pick((
            f"这个模型在本机没有{suffix}：先 ollama pull 模型名，再回到这里填同一个名字",
            f"Model not found locally{suffix}: run `ollama pull <model>` first, then use that name here",
        ))
    if status == 401 or status == 403:
        return i18n.pick((
            f"本机服务拒绝了请求{suffix}：确认 Ollama 没有开鉴权，地址是 http:// 本机端口",
            f"The local server rejected the request{suffix}: check the address and that auth is off",
        ))
    if status >= 500:
        return i18n.pick((
            f"本机模型跑失败了{suffix}：显存/内存不够时换更小的模型（如 3B）再试",
            f"The local model failed{suffix}: try a smaller model (e.g. 3B) if memory is tight",
        ))
    return i18n.pick((
        f"本机服务返回 {status}{suffix}：检查 Ollama 版本与模型名",
        f"The local server returned {status}{suffix}: check the Ollama version and model name",
    ))


def _ollama_connection_error(exc: BaseException, base: str) -> str:
    """把「连不上」翻成能照做的步骤。"""
    reason = getattr(exc, "reason", exc)
    return i18n.pick((
        f"连不上本机 Ollama（{base}）：先确认已安装 Ollama 且 `ollama serve` 在运行，"
        f"地址默认 http://localhost:11434（原始错误：{reason}）",
        f"Cannot reach local Ollama at {base}: install Ollama, run `ollama serve`, "
        f"default address http://localhost:11434 (error: {reason})",
    ))


def list_ollama_models(base: str = DEFAULT_OLLAMA_BASE, timeout: float = 8) -> list[str]:
    """读 GET {base}/api/tags：既列本机已拉取的模型，也用来判断服务有没有起来。"""
    base = (base or DEFAULT_OLLAMA_BASE).strip().rstrip("/")
    url = f"{base}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 404:
            detail = f"（{body[:120].strip()}）" if body.strip() else ""
            raise RuntimeError(i18n.pick((
                f"这个地址上没有 Ollama 的 /api/tags（404）{detail}："
                f"确认地址填的是 http://localhost:11434，而不是别的服务",
                f"No /api/tags at this address (404){detail}: make sure it is http://localhost:11434",
            ))) from exc
        raise RuntimeError(_ollama_http_error(exc.code, body)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(_ollama_connection_error(exc, base)) from exc
    except TimeoutError as exc:
        raise RuntimeError(i18n.pick((
            "本机 Ollama 没响应（8 秒超时）：服务卡住了就重启一下 ollama",
            "Local Ollama did not respond within 8s: restart it",
        ))) from exc
    try:
        payload = json.loads(raw)
        models = payload.get("models") or []
        names = []
        for item in models:
            name = str((item or {}).get("name") or (item or {}).get("model") or "").strip()
            if name:
                names.append(name)
        return names
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(i18n.pick((
            "返回内容看不懂（不是 Ollama 的 /api/tags 结构），确认地址填的是 Ollama 而不是别的服务",
            "Unexpected response from /api/tags: check the address really is Ollama",
        ))) from exc


def call_ollama(
    sentence: str,
    *,
    model: str,
    base: str = DEFAULT_OLLAMA_BASE,
    style: str = "natural",
    chars: int = 200,
    timeout: int = OLLAMA_TIMEOUT,
) -> str:
    """走 Ollama 原生 /api/chat（stream=false），解析 message.content。"""
    model = (model or "").strip()
    if not model:
        raise RuntimeError(i18n.pick((
            "还没填本机模型名：在「模型设置」里填 ollama list 里看到的名字（如 qwen2.5:7b）",
            "No local model yet: fill in a name from `ollama list` (e.g. qwen2.5:7b)",
        )))
    base = (base or DEFAULT_OLLAMA_BASE).strip().rstrip("/")
    url = f"{base}/api/chat"
    body = json.dumps(
        {
            "model": model,
            "messages": build_messages(sentence, style, chars),
            "stream": False,
            "options": {"temperature": 0.75},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_ollama_http_error(exc.code, exc.read().decode("utf-8", "replace"))) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(_ollama_connection_error(exc, base)) from exc
    except TimeoutError as exc:
        raise RuntimeError(i18n.pick((
            f"本机模型两分钟没写完（{model}）：换更小的模型，或把目标长度调短一点",
            f"The local model did not finish within 120s ({model}): try a smaller model or shorter length",
        ))) from exc

    try:
        payload = json.loads(raw)
        content = payload["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(i18n.pick((
            "返回内容看不懂（不是 Ollama /api/chat 的结构），确认版本不低于 0.1.24",
            "Unexpected response: not an Ollama /api/chat payload; check the Ollama version",
        ))) from exc

    text = clean_output(str(content))
    if not text:
        raise RuntimeError(i18n.pick((
            "本机模型返回了空内容：这个模型可能不适合写文案，换一个再试",
            "The local model returned nothing: try another model",
        )))
    return text


def call_model(sentence: str, settings: dict, style: str, chars: int) -> str:
    """按设置里的 provider 分派到方舟或本机 Ollama。"""
    if provider(settings) == "ollama":
        return call_ollama(
            sentence,
            model=str(settings.get("ai_ollama_model", "")).strip(),
            base=str(settings.get("ai_ollama_base", DEFAULT_OLLAMA_BASE)).strip(),
            style=style,
            chars=chars,
        )
    return call_ark(
        sentence,
        api_key=resolved_key(settings),
        model=str(settings.get("ai_model", "")).strip(),
        base=str(settings.get("ai_base", DEFAULT_BASE)).strip(),
        style=style,
        chars=chars,
    )


class WriterJob(QThread):
    """后台扩写任务：界面只收信号，拖动窗口不掉帧。"""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, sentence: str, settings: dict, style: str, chars: int, parent=None):
        super().__init__(parent)
        self._sentence = sentence
        self._settings = dict(settings)
        self._style = style
        self._chars = chars

    def run(self) -> None:
        try:
            text = call_model(self._sentence, self._settings, self._style, self._chars)
        except RuntimeError as exc:
            self.failed.emit(str(exc))
        except BaseException as exc:  # noqa: BLE001 - 线程里必须兜住所有异常
            self.failed.emit(i18n.pick((f"生成失败：{exc}", f"Generation failed: {exc}")))
        else:
            self.succeeded.emit(text)


def ollama_installed() -> bool:
    """判断本机装没装 Ollama：先看 PATH，再查默认安装目录。"""
    if shutil.which("ollama"):
        return True
    local = os.environ.get("LOCALAPPDATA", "")
    return bool(local) and (Path(local) / "Programs" / "Ollama" / "ollama.exe").exists()


class DownloadCancelled(Exception):
    """用户点了取消：线程里当正常结束处理，不刷成错误。"""


def parse_proxy_server(server: str) -> str | None:
    """把注册表里的 ProxyServer 值拆成可用的 host:port。

    可能形如 "127.0.0.1:7890"，也可能是 "http=...;https=...;ftp=..."。
    """
    server = (server or "").strip()
    if not server:
        return None
    if "=" in server:
        parts = dict(p.split("=", 1) for p in server.split(";") if "=" in p)
        server = parts.get("https") or parts.get("http") or ""
    return server.strip() or None


def system_proxy() -> str | None:
    """读 Windows 的系统代理（Clash 之类会让 IE 设置里留 ProxyServer）。

    urllib 默认只认环境变量，不认系统代理；这里补上，开了代理的用户才能下得动。
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "")
    except OSError:
        return None
    if not enable or not server:
        return None
    return parse_proxy_server(server)


def download_installer(
    dest: Path = INSTALLER_PATH,
    progress=None,
    cancel: threading.Event | None = None,
    timeout: int = 30,
) -> Path:
    """下载官方 OllamaSetup.exe，边下边报进度；先写 .part，完成后原子改名。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(INSTALLER_URL, headers={"User-Agent": "EdgeTTSStudio/1.0"})
    proxy = system_proxy()
    handlers = [urllib.request.ProxyHandler(
        {"http": f"http://{proxy}", "https": f"http://{proxy}"})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as fh:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
        os.replace(part, dest)
    except DownloadCancelled:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    except urllib.error.HTTPError as exc:
        try:
            part.unlink()
        except OSError:
            pass
        raise RuntimeError(i18n.pick((
            f"下载安装包失败（HTTP {exc.code}）：可以稍后再试，或手动到 ollama.com/download 下载",
            f"Download failed (HTTP {exc.code}): retry later or get it from ollama.com/download",
        ))) from exc
    except urllib.error.URLError as exc:
        try:
            part.unlink()
        except OSError:
            pass
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(i18n.pick((
            f"下载安装包失败（连不上 ollama.com：{reason}）：检查网络/代理，或手动下载",
            f"Download failed (cannot reach ollama.com: {reason}): check network/proxy, or download manually",
        ))) from exc
    except TimeoutError as exc:
        try:
            part.unlink()
        except OSError:
            pass
        raise RuntimeError(i18n.pick((
            "下载安装包超时：网络太慢，稍后再试或手动下载",
            "Download timed out: slow network, retry later or download manually",
        ))) from exc
    except OSError as exc:
        try:
            part.unlink()
        except OSError:
            pass
        raise RuntimeError(i18n.pick((
            f"安装包写不进磁盘（{exc}）：检查临时目录权限与剩余空间",
            f"Cannot write the installer ({exc}): check the temp folder and free space",
        ))) from exc
    return dest


class InstallJob(QThread):
    """后台下载安装包：进度回报给界面，取消靠 threading.Event。"""

    progress = Signal(int, int)      # 已下字节, 总字节（0 表示服务端没给长度）
    done = Signal(str)               # 安装包路径
    failed = Signal(str)

    def __init__(self, dest: Path = INSTALLER_PATH, parent=None):
        super().__init__(parent)
        self._dest = Path(dest)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            path = download_installer(
                self._dest,
                progress=lambda done, total: self.progress.emit(int(done), int(total)),
                cancel=self._cancel,
            )
        except DownloadCancelled:
            self.failed.emit(i18n.pick(("已取消下载安装包", "Download cancelled")))
        except RuntimeError as exc:
            self.failed.emit(str(exc))
        except BaseException as exc:  # noqa: BLE001
            self.failed.emit(i18n.pick((f"下载失败：{exc}", f"Download failed: {exc}")))
        else:
            self.done.emit(str(path))


class DetectJob(QThread):
    """后台读 /api/tags：本机没起服务时最多等 8 秒，别冻住界面。"""

    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self._base = base

    def run(self) -> None:
        try:
            names = list_ollama_models(self._base)
        except RuntimeError as exc:
            self.failed.emit(str(exc))
        except BaseException as exc:  # noqa: BLE001
            self.failed.emit(i18n.pick((f"检测失败：{exc}", f"Test failed: {exc}")))
        else:
            self.succeeded.emit(names)
