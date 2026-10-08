"""MiliastraGME 控制台 —— 核心引擎层。

这一层只做三件事：
1. 以 importlib 方式加载上游 MiliastraGME 包（目录名带连字符，不能直接 import）；
2. 把上游的 inject / restore / params / status / 配置读写封装成可调用的函数；
3. 提供后台线程任务、子进程调用、UAC 提权入口。

UI 层不应直接碰上游模块，避免上游改版时到处崩。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

CORE_PACKAGE_ALIAS = "gme_core"

# 需要管理员权限的子命令
ADMIN_COMMANDS = {"inject", "restore"}

PARAM_KEYS: tuple[str, ...] = (
    "aec",
    "agc",
    "ans",
    "ains",
    "vad",
    "fec",
    "frame",
    "sample_rate",
    "channel",
    "codec_prof",
    "kbps",
    "bitrate",
    "jitter_init",
    "jitter_min",
    "jitter_max",
)

PARAM_LABELS: dict[str, tuple[str, str]] = {
    "aec": ("回声消除", "AEC：采集端的回声消除，关掉可避免音乐被削"),
    "agc": ("自动增益", "AGC：自动音量，关掉可保留原始动态"),
    "ans": ("普通降噪", "ANS：传统降噪，会吃掉高频细节"),
    "ains": ("AI 降噪", "AINS：AI 降噪，对人声/音乐的损伤更明显"),
    "vad": ("静音检测", "VAD：静音检测/不连续发送，关掉可避免乐句开头被吞"),
    "fec": ("丢包保护", "FEC：抗丢包冗余，建议保持开启"),
    "frame": ("帧长（ms）", "编码帧长，一般 20 或 40"),
    "sample_rate": ("采样率（Hz）", "48000 为高音质档，16000 为默认通话档"),
    "channel": ("声道数", "1=单声道，2=双声道"),
    "codec_prof": ("编码模式", "codec_prof，默认配置里为 4129"),
    "kbps": ("码率（kbps）", "目标码率，需与 bitrate 保持 kbps*1000 的关系"),
    "bitrate": ("码率（bps）", "实际传入 SDK 的码率，必须 >= kbps*1000"),
    "jitter_init": ("缓冲初始值（ms）", "jitter 缓冲初始值"),
    "jitter_min": ("缓冲下限（ms）", "jitter 缓冲下限"),
    "jitter_max": ("缓冲上限（ms）", "jitter 缓冲上限"),
}

TOGGLE_KEYS = ("aec", "agc", "ans", "ains", "vad", "fec")


# --------------------------------------------------------------------------- #
# 路径与包加载
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Layout:
    """上游仓库的关键路径。

    注意：上游代码就在仓库根目录（``audio_params.py`` / ``gme_config.py`` 等），
    没有额外一层包目录，所以 ``core_dir`` 就是 ``root``。
    """

    root: Path

    @property
    def gui_dir(self) -> Path:
        return self.root / "gui"

    @property
    def core_dir(self) -> Path:
        """上游代码所在目录（= 仓库根目录）。"""

        return self.root

    @property
    def entry(self) -> Path:
        """上游 CLI 入口。"""

        return self.root / "__main__.py"

    @property
    def audio_params(self) -> Path:
        return self.root / "audio_params.json"

    @property
    def settings(self) -> Path:
        return self.root / "settings.json"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def backup_dir(self) -> Path:
        return self.root / "backups"

    @property
    def status_file(self) -> Path:
        return self.data_dir / "gme_voice_auto_injector_status.json"

    @property
    def manifest_file(self) -> Path:
        return self.data_dir / "gme_voice_auto_injector_manifest.json"

    @property
    def hosts_file(self) -> Path:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        return Path(system_root) / "System32" / "drivers" / "etc" / "hosts"


def discover_layout(start: Path | None = None) -> Layout:
    """从 gui/ 目录向上找到上游仓库根目录。"""

    here = (start or Path(__file__).resolve().parent).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "audio_params.py").exists() and (candidate / "gme_config.py").exists():
            return Layout(candidate)
    raise FileNotFoundError("未找到 MiliastraGME 仓库根目录（缺少 audio_params.py / gme_config.py）")


def mirror_core_package(layout: Layout, alias: str = CORE_PACKAGE_ALIAS) -> Path:
    """以合法包名加载上游代码，使 ``from .xxx import`` 相对导入可用。

    上游目录名带连字符（``miliastra-gme``）无法直接 import，
    ``importlib`` 允许指定 ``submodule_search_locations``，于是包名与目录名可以解耦。
    """

    import importlib.util

    if alias in sys.modules:
        return Path(sys.modules[alias].__file__).resolve()

    # 目录名合法时也可以直接 import，这里统一走 importlib 以免受 sys.path 顺序影响
    root_str = str(layout.root)
    if root_str not in sys.path:
        sys.path.append(root_str)

    spec = importlib.util.spec_from_file_location(
        alias,
        layout.root / "__init__.py",
        submodule_search_locations=[root_str],
    )
    if spec is None or spec.loader is None:
        raise ImportError("无法为 MiliastraGME 建立模块 spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return Path(module.__file__).resolve()


# --------------------------------------------------------------------------- #
# 子进程 / 提权
# --------------------------------------------------------------------------- #

@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    seconds: float
    started_at: datetime = field(default_factory=datetime.now)

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def text(self) -> str:
        chunks = [part for part in (self.stdout, self.stderr) if part and part.strip()]
        return "\n".join(chunk.rstrip() for chunk in chunks)


def python_executable() -> str:
    exe = sys.executable or "python"
    if exe.lower().endswith("pythonw.exe"):
        console = Path(exe).with_name("python.exe")
        if console.exists():
            return str(console)
    return exe


def no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def run_cli(layout: Layout, command: str) -> CommandResult:
    """调用上游 CLI 子进程（用于日志留档，UI 主逻辑走进程内 API）。"""

    args = [python_executable(), str(layout.entry), command]
    started = time.perf_counter()
    proc = subprocess.run(
        args,
        cwd=str(layout.core_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=no_window_flags(),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return CommandResult(
        command=args,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        seconds=time.perf_counter() - started,
    )


def elevated_inner_command(layout: Layout, command: str, keep_open: bool = True) -> str:
    """拼出提权窗口里要执行的 PowerShell 命令行。"""

    parts = [
        f'Set-Location -LiteralPath "{layout.core_dir}"',
        f'Write-Host "[MiliastraGME] 以管理员身份执行 {command}" -ForegroundColor Cyan',
        f'& "{python_executable()}" "{layout.entry}" {command}',
    ]
    if keep_open:
        parts.append('Write-Host "[{0} 结束] 可关闭此窗口" -ForegroundColor Cyan'.format(command))
        parts.append("Read-Host '按回车关闭'")
    return "; ".join(parts)


def run_elevated(layout: Layout, command: str, keep_open: bool = True) -> bool:
    """通过 UAC 提权执行 inject / restore。

    会弹出系统 UAC 确认框；确认后开一个独立控制台窗口执行。
    提权进程的输出无法回传到本进程，所以窗口默认保持打开让用户自己看。
    """

    if os.name != "nt":
        raise RuntimeError("提权仅在 Windows 上可用")

    import ctypes

    inner = elevated_inner_command(layout, command, keep_open)
    params = f'-NoProfile -ExecutionPolicy Bypass -Command "{inner}"'
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe", params, str(layout.core_dir), 1
    )
    return int(result) > 32


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_self_as_admin() -> bool:
    """把 GUI 自身以管理员身份重启。"""

    if os.name != "nt":
        return False
    import ctypes

    params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", python_executable(), params, str(Path.cwd()), 1
    )
    return int(result) > 32


def reveal_in_explorer(path: Path) -> bool:
    """在资源管理器中定位文件或打开目录。"""

    if not path.exists():
        return False
    try:
        if path.is_dir():
            os.startfile(str(path))  # noqa: S606 - Windows 专用
        else:
            subprocess.Popen(["explorer", "/select,", str(path)], creationflags=no_window_flags())
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 后台任务
# --------------------------------------------------------------------------- #

class TaskContext:
    """任务内部用来回报进度的小工具。"""

    def __init__(self, report: Callable[[str, str], None]) -> None:
        self._report = report

    def log(self, message: str, level: str = "info") -> None:
        self._report(level, message)

    def check_cancelled(self) -> None:
        return None


class TaskRunner(QObject):
    """后台任务队列：一个常驻 Python 线程按 FIFO 顺序执行任务，结果用 Qt 信号回传。

    刻意不使用 QThread + moveToThread：QThread 的槽调用与对象所有权很容易踩坑，
    而 Qt 信号本身线程安全（跨线程自动排队到接收者所在线程），
    所以让 Python 线程只负责算，信号只负责回传，队列保证同时只有一个任务在跑。
    """

    progress = Signal(str, str)  # level, message
    done = Signal(str, object)  # task name, result
    failed = Signal(str, str)  # task name, error
    busy_changed = Signal(bool, str)  # busy, label

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: deque[tuple[str, str, Callable[[TaskContext], Any]]] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._busy = False
        self._label = ""
        self._thread = threading.Thread(target=self._loop, name="miliastra-tasks", daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    def start(self, name: str, label: str, fn: Callable[[TaskContext], Any]) -> bool:
        with self._lock:
            self._queue.append((name, label, fn))
            idle = not self._busy
            self._wake.set()
        if idle:
            self.busy_changed.emit(True, label)
        else:
            self.progress.emit("dim", f"已排队：{label}")
        return True

    # ---- 后台线程 ---- #

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                item = self._queue.popleft() if self._queue else None
            if item is None:
                self._wake.wait(0.2)
                self._wake.clear()
                continue

            name, label, fn = item
            with self._lock:
                self._busy = True
                self._label = label
            self.busy_changed.emit(True, label)
            started = time.perf_counter()
            try:
                result = fn(TaskContext(lambda level, message: self.progress.emit(level, message)))
            except Exception as exc:  # noqa: BLE001 - 要原样告诉用户
                self.failed.emit(name, f"{type(exc).__name__}: {exc}")
            else:
                self.done.emit(name, result)
            finally:
                self.progress.emit("dim", f"「{label}」耗时 {time.perf_counter() - started:.2f}s")

            with self._lock:
                self._busy = bool(self._queue)
                next_label = self._queue[0][1] if self._queue else ""
                self._label = next_label
            self.busy_changed.emit(bool(next_label), next_label)

    def shutdown(self, timeout: float = 5.0) -> None:
        """退出前停止消费队列（线程是 daemon，不会阻止进程退出）。"""

        self._stop.set()
        self._wake.set()
        self._thread.join(timeout)


# --------------------------------------------------------------------------- #
# 配置读写（进程内，不依赖子进程）
# --------------------------------------------------------------------------- #

class GmeEngine:
    """上游能力的门面。所有方法都在调用线程里同步执行。"""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout
        mirror_core_package(layout)

    # ---- 动态导入，保证 sys.path 已就绪 ---- #

    @staticmethod
    def _mod(name: str):
        import importlib

        return importlib.import_module(f"{CORE_PACKAGE_ALIAS}.{name}")

    # ---- 基础 ---- #

    def load_settings(self) -> dict[str, str]:
        return self._mod("paths").load_settings()

    def save_settings(self, payload: dict[str, str]) -> dict[str, str]:
        clean = {key: str(value).strip() for key, value in payload.items()}
        self.layout.settings.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.load_settings()

    def detect_and_store_game_dir(self) -> tuple[Path | None, bool]:
        """探测游戏目录；探到了就写进 settings.json，让 inject 能覆盖游戏侧文件。

        返回 ``(目录, 是否写入成功)``。探测顺序：

        1. 上游 ``paths.detect_game_dir_from_process()``（Win32_Process）
        2. ``Get-Process`` 的 ``Path`` / ``MainModule`` 兜底
        3. 米哈游启动器安装目录 + 注册表（进程不可读时的最后手段）
        """

        paths = self._mod("paths")
        detected = paths.detect_game_dir_from_process()
        if detected is None:
            detected = self._detect_game_dir_by_process_path()
        if detected is None:
            detected = self._detect_game_dir_from_launcher()

        if detected is None:
            return None, False

        settings = self.load_settings()
        if settings.get("game_dir") == str(detected):
            return detected, False
        settings["game_dir"] = str(detected)
        self.save_settings(settings)
        return detected, True

    @staticmethod
    def _detect_game_dir_by_process_path() -> Path | None:
        """兜底一：直接用 Get-Process 的 Path / MainModule.FileName。"""

        if os.name != "nt":
            return None
        scripts = (
            "Get-Process -Name YuanShen,GenshinImpact -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path } | Select-Object -First 1 -ExpandProperty Path",
            "$procs = Get-Process -Name YuanShen,GenshinImpact -ErrorAction SilentlyContinue; "
            "foreach ($p in $procs) { try { $p.MainModule.FileName } catch {} }",
        )
        for script in scripts:
            for value in GmeEngine._run_powershell_lines(script):
                if value.lower().endswith(".exe") and Path(value).exists():
                    return Path(value).parent
        return None

    @staticmethod
    def _detect_game_dir_from_launcher() -> Path | None:
        """兜底二：不依赖进程，直接找米哈游启动器的游戏目录。"""

        if os.name != "nt":
            return None

        candidates: list[Path] = []

        # 注册表：启动器安装位置
        script = (
            "$keys = @("
            "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
            "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
            "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'); "
            "Get-ItemProperty $keys -ErrorAction SilentlyContinue | "
            "Where-Object { $_.DisplayName -match 'Genshin|原神|miHoYo' } | "
            "Select-Object -ExpandProperty InstallLocation -ErrorAction SilentlyContinue"
        )
        for value in GmeEngine._run_powershell_lines(script):
            if value:
                candidates.append(Path(value))

        # 常见位置
        for root in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
            Path("D:\\"),
            Path("E:\\"),
        ):
            candidates.append(root / "miHoYo Launcher")
            candidates.append(root / "Genshin Impact")
            candidates.append(root / "Program Files" / "miHoYo Launcher")

        exe_names = ("YuanShen.exe", "GenshinImpact.exe")
        for base in candidates:
            if not base.exists():
                continue
            for exe in exe_names:
                direct = base / exe
                if direct.exists():
                    return direct.parent
            for pattern in ("games/*/", "*/"):
                try:
                    children = list(base.glob(pattern))
                except OSError:
                    continue
                for child in children:
                    for exe in exe_names:
                        if (child / exe).exists():
                            return child
        return None

    @staticmethod
    def _run_powershell_lines(script: str) -> list[str]:
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                creationflags=no_window_flags(),
                timeout=30,
            )
        except Exception:  # noqa: BLE001
            return []
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]

    def load_params_raw(self) -> dict[str, Any]:
        return json.loads(self.layout.audio_params.read_text(encoding="utf-8"))

    def save_params_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.layout.audio_params.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.load_params_raw()

    def validate_params(self, payload: dict[str, Any]) -> dict[str, int]:
        return self._mod("audio_params").validate_audio(payload)

    def audio_profile(self) -> dict[str, Any]:
        return self._mod("audio_params").active_audio_info()

    def full_status(self) -> dict[str, Any]:
        # status.py 依赖 TARGET_AUDIO 已填充，必须先加载参数
        self._mod("audio_params").load_audio_params()
        return self._mod("status").full_status()

    def inject(self, ctx: TaskContext | None = None) -> dict[str, Any]:
        params = self._mod("audio_params")
        config = self._mod("gme_config")
        hosts = self._mod("hosts")
        common = self._mod("common")
        constants = self._mod("constants")

        def log(message: str, level: str = "info") -> None:
            if ctx is not None:
                ctx.log(message, level)

        common.ensure_dirs()
        log("读取并校验 audio_params.json …")
        profile = params.load_audio_params()
        log(f"方案：{profile['name']}（{profile['target_text']}）")

        log("修补 %APPDATA%\\GME 下的 gmesdk_control_*.config …")
        configs = config.install_configs()
        for item in configs.get("control", []):
            tag = "已改写" if item.get("changed") else "无需改动"
            log(f"  · {item['path']} → {tag}", "ok" if item.get("changed") else "info")
        for item in configs.get("av_config", []):
            tag = "已写入" if item.get("changed") else "内容一致"
            log(f"  · av_config：{item['path']} → {tag}", "ok" if item.get("changed") else "info")

        log("写入 hosts 屏蔽段（阻断 GME 远程配置域名）…")
        hosts_result = hosts.install_hosts_block()
        if hosts_result.get("changed"):
            log(f"  · hosts 已更新，备份：{hosts_result.get('backup')}", "ok")
        else:
            log("  · hosts 已是目标状态", "info")

        log("汇总运行状态 …")
        status = self.full_status()
        payload = {
            "time": common.now(),
            "action": "inject",
            "mode": "gui",
            "attempt": 1,
            "audio_profile": profile,
            "config": configs,
            "hosts": hosts_result,
            "status": status,
        }
        common.write_json(constants.MANIFEST_PATH, payload)
        common.write_json(constants.STATUS_PATH, status)
        log("已完成 inject，状态文件已刷新。", "ok")
        return payload

    def restore(self, ctx: TaskContext | None = None) -> dict[str, Any]:
        hosts = self._mod("hosts")
        config = self._mod("gme_config")
        common = self._mod("common")
        constants = self._mod("constants")

        def log(message: str, level: str = "info") -> None:
            if ctx is not None:
                ctx.log(message, level)

        self._mod("audio_params").load_audio_params()
        log("移除 hosts 中的 GME 屏蔽段 …")
        hosts_result = hosts.remove_hosts_block()
        log(f"  · hosts 屏蔽段：{'已移除' if hosts_result.get('removed') else '本来就没有'}", "ok")

        log("移除本工具写入的 av_config.json …")
        av = config.remove_local_av_config()
        for item in av:
            log(f"  · {item['path']} → {'已删除' if item.get('removed') else '不存在'}", "info")

        status = self.full_status()
        payload = {
            "time": common.now(),
            "action": "restore",
            "hosts": hosts_result,
            "local_av_configs": av,
            "status": status,
        }
        common.write_json(constants.STATUS_PATH, status)
        log("restore 完成：注意 gmesdk_control_*.config 不会被自动回滚。", "warn")
        return payload

    # ---- 关闭全部音频处理 ---- #

    def apply_audio_off(self, ctx: TaskContext | None = None) -> dict[str, Any]:
        """把所有 GME 控制配置 + av_config.json 里的音频处理开关全部关掉。

        与上游 ``inject`` 的区别：这里**不动 hosts**，只做「处理关干净」这一件事，
        并且额外覆盖上游漏掉的 ``dtx`` 和 ``net`` 段。
        """

        from . import audio_off

        gme_config = self._mod("gme_config")
        paths = self._mod("paths")
        common = self._mod("common")

        def log(message: str, level: str = "info") -> None:
            if ctx is not None:
                ctx.log(message, level)

        # 1) 控制配置
        base = paths.gme_dir()
        configs: list[dict] = []
        total_changes: list[dict] = []
        if not base.exists():
            log(f"GME 数据目录不存在：{base}", "warn")
        else:
            for path in sorted(base.glob("gmesdk_control_*.config")):
                config = gme_config.load_encoded_config(path)
                changes = audio_off.force_off_config(config)
                patched = gme_config.dump_encoded_config(config)
                changed = path.read_bytes() != patched
                backup = common.backup_file(path, "control") if changed else None
                if changed:
                    gme_config.make_writable(path)
                    try:
                        path.write_bytes(patched)
                    finally:
                        gme_config.make_readonly(path)
                else:
                    gme_config.make_readonly(path)
                for item in changes:
                    item["config"] = path.name
                total_changes.extend(changes)
                configs.append(
                    {
                        "path": str(path),
                        "changed": changed,
                        "backup": str(backup) if backup else None,
                        "changes": changes,
                        "profile_count": len(audio_off.iter_profiles(config)),
                    }
                )
                state = "已改写" if changed else "本来就全关"
                log(f"  · {path.name}：{state}（{len(changes)} 处开关被关）", "ok" if changed else "info")
                for item in changes:
                    log(
                        f"      {audio_off.label(item['key'])}：{item['before']} → 0",
                        "dim",
                    )

        # 2) av_config.json（本地覆盖配置）
        av_results: list[dict] = []
        payload_config = gme_config.source_config()
        audio_off.force_off_config(payload_config)
        payload = json.dumps(payload_config, ensure_ascii=False, indent=2)
        for path in paths.local_av_config_targets():
            path.parent.mkdir(parents=True, exist_ok=True)
            current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
            changed = current != payload
            backup = gme_config.backup_file(path, "av_config") if changed else None
            if changed:
                gme_config.make_writable(path)
                path.write_text(payload, encoding="utf-8")
            gme_config.make_readonly(path)
            av_results.append(
                {
                    "path": str(path),
                    "changed": changed,
                    "backup": str(backup) if backup else None,
                    "readonly": not bool(path.stat().st_mode & 0o200),
                }
            )
            log(f"  · av_config：{path} → {'已写入' if changed else '内容一致'}", "ok" if changed else "info")

        # 3) 记录一份清单
        status = self.audio_processing_status()
        try:
            game = paths.game_dir()
        except Exception:  # noqa: BLE001
            game = None
        manifest = {
            "time": common.now(),
            "action": "audio_off",
            "changes": total_changes,
            "configs": configs,
            "av_configs": av_results,
            "game_dir": str(game) if game else None,
            "status": status,
        }
        common.write_json(self.layout.data_dir / "audio_off_manifest.json", manifest)
        log(audio_off.summarize(total_changes), "ok" if total_changes else "info")
        if game is None:
            log(
                "提示：没探测到游戏目录，游戏安装目录下的 av_config.json 没有写入。"
                "游戏运行时再点一次，或在「高级配置」里手动填 game_dir。",
                "warn",
            )
        log("注意：本操作不改 hosts，如需锁死远程配置请另外执行 inject。", "warn")
        return manifest

    def audio_processing_status(self) -> dict[str, Any]:
        """汇总「游戏自带音频处理」在配置层与运行层的实际状态。"""

        from . import audio_off

        paths = self._mod("paths")
        gme_config = self._mod("gme_config")

        config_profiles: list[dict] = []
        config_files: list[str] = []
        base = paths.gme_dir()
        if base.exists():
            for path in sorted(base.glob("gmesdk_control_*.config")):
                try:
                    config = gme_config.load_encoded_config(path)
                except Exception:  # noqa: BLE001
                    continue
                config_files.append(path.name)
                for row in gme_config.summarize_config(config):
                    config_profiles.append(row)

        runtime_sample: dict[str, Any] = {}
        runtime_error: str | None = None
        # 上游的 status 模块依赖 TARGET_AUDIO 这个模块级全局，必须先加载参数。
        # 加载失败（比如 audio_params.json 被别人改坏）不应该让整个核验挂掉，
        # 但也不能静默吞掉——把原因带出去给界面显示。
        try:
            self._mod("audio_params").load_audio_params()
        except Exception as exc:  # noqa: BLE001
            runtime_error = f"参数文件不可用：{type(exc).__name__}: {exc}"
        else:
            try:
                runtime_sample = self._mod("status").runtime_log_status().get("target_sample") or {}
            except Exception as exc:  # noqa: BLE001
                runtime_error = f"读取运行日志失败：{type(exc).__name__}: {exc}"

        return {
            "config_files": config_files,
            "config_profiles": config_profiles,
            "config_state": audio_off.processing_state(config_profiles),
            "runtime_sample": runtime_sample,
            "runtime_error": runtime_error,
            "runtime_state": audio_off.processing_state([runtime_sample]) if runtime_sample else {},
            "keys": list(audio_off.AUDIO_PROCESS_KEYS),
        }

    # ---- 只读视图 ---- #

    def decoded_control_configs(self) -> list[dict[str, Any]]:
        """把编码过的控制配置解码出来给 UI 看。"""

        gme_config = self._mod("gme_config")
        paths = self._mod("paths")
        base = paths.gme_dir()
        rows: list[dict[str, Any]] = []
        if not base.exists():
            return rows
        for path in sorted(base.glob("gmesdk_control_*.config")):
            entry: dict[str, Any] = {
                "path": str(path),
                "name": path.name,
                "size": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "readonly": not bool(path.stat().st_mode & 0o200),
                "error": None,
                "profiles": [],
                "sequence": None,
            }
            try:
                config = gme_config.load_encoded_config(path)
                entry["profiles"] = gme_config.summarize_config(config)
                entry["sequence"] = config.get("data", {}).get("sequence")
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(entry)
        return rows

    def local_av_configs(self) -> list[dict[str, Any]]:
        paths = self._mod("paths")
        rows = []
        for path in paths.local_av_config_targets():
            rows.append(
                {
                    "path": str(path),
                    "exists": path.exists(),
                    "size": path.stat().st_size if path.exists() else 0,
                    "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    if path.exists()
                    else None,
                }
            )
        return rows

    def hosts_block(self) -> dict[str, Any]:
        constants = self._mod("constants")
        text = self.layout.hosts_file.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        inside = False
        block: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped == constants.HOSTS_BEGIN:
                inside = True
                block.append(line)
                continue
            if stripped == constants.HOSTS_END:
                block.append(line)
                inside = False
                continue
            if inside:
                block.append(line)
        return {
            "path": str(self.layout.hosts_file),
            "blocked_hosts": list(constants.BLOCKED_HOSTS),
            "installed": constants.HOSTS_BEGIN in text,
            "block": "\n".join(block),
        }

    def latest_log_path(self) -> Path | None:
        paths = self._mod("paths")
        base = paths.gme_dir()
        if not base.exists():
            return None
        logs = sorted(base.glob("GMESDK_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
        return logs[0] if logs else None

    def tail_log(self, limit: int = 400, pattern: str = "") -> tuple[Path | None, list[str]]:
        log = self.latest_log_path()
        if log is None:
            return None, []
        from collections import deque

        buffer: deque[str] = deque(maxlen=limit)
        needle = pattern.strip().lower()
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if needle and needle not in line.lower():
                    continue
                buffer.append(line.rstrip("\n"))
        return log, list(buffer)

    def list_backups(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.layout.backup_dir.exists():
            return rows
        for path in sorted(self.layout.backup_dir.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True):
            name = path.name
            if ".hosts." in name:
                kind = "hosts"
            elif ".control." in name:
                kind = "GME 控制配置"
            elif ".av_config." in name:
                kind = "av_config.json"
            else:
                kind = "其他"
            rows.append(
                {
                    "path": str(path),
                    "name": name,
                    "kind": kind,
                    "size": path.stat().st_size,
                    "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return rows


# --------------------------------------------------------------------------- #
# 备份回滚
# --------------------------------------------------------------------------- #

def resolve_rollback_target(engine: "GmeEngine", layout: Layout, source: Path) -> Path | None:
    """从备份文件名推断它原本属于哪个路径。

    上游 ``backup_file`` 的命名规则是 ``<原文件名>.<tag>.<时间戳>.bak``，但备份里
    没有记录原路径，只能靠文件名约定 + 当前 settings 推断。
    """

    name = source.name
    if not name.endswith(".bak"):
        return None
    stem = name[: -len(".bak")]

    if stem.startswith("hosts.hosts."):
        return layout.hosts_file

    core_name = stem
    for tag in (".control.", ".av_config."):
        if tag in core_name:
            core_name = core_name.split(tag)[0]
            break

    if core_name.startswith("gmesdk_control_"):
        try:
            return Path(engine._mod("paths").gme_dir()) / core_name
        except Exception:  # noqa: BLE001
            return None

    if core_name == "av_config.json":
        try:
            targets = engine._mod("paths").local_av_config_targets()
        except Exception:  # noqa: BLE001
            return None
        return targets[0] if targets else None

    return None


# --------------------------------------------------------------------------- #
# 便捷函数
# --------------------------------------------------------------------------- #

def processing_table_rows(status: dict[str, Any]) -> list[tuple[list[str], str]]:
    """把 audio_processing_status() 的结果整理成表格行。

    返回 ``[(cells, tone), ...]``，tone 为 ``ok`` / ``warn`` / ``muted``。
    """

    from . import audio_off

    config_state = status.get("config_state") or {}
    runtime_state = status.get("runtime_state") or {}
    profiles = status.get("config_profiles") or []
    rows: list[tuple[list[str], str]] = []

    def cell(state: dict[str, Any], key: str) -> str:
        info = state.get(key) or {}
        if not info.get("present"):
            return "—"
        return "关" if info.get("all_off") else "开"

    def tone_for(key: str) -> str:
        info = config_state.get(key) or {}
        rt = runtime_state.get(key) or {}
        if not info.get("present") and not rt.get("present"):
            return "muted"
        if info.get("any_on") or rt.get("any_on"):
            return "warn"
        return "ok"

    for key in audio_off.AUDIO_PROCESS_KEYS:
        config_text = cell(config_state, key)
        runtime_text = cell(runtime_state, key)
        config_present = bool((config_state.get(key) or {}).get("present"))
        runtime_present = bool((runtime_state.get(key) or {}).get("present"))
        runtime_on = bool((runtime_state.get(key) or {}).get("any_on"))
        config_on = bool((config_state.get(key) or {}).get("any_on"))

        if not profiles and not runtime_present:
            # 一个控制配置都没扫到：别谎称「SDK 未暴露」，真实原因是文件不存在
            conclusion = "没有扫到控制配置文件，先执行一次「关闭全部音频处理」或 inject"
        elif not profiles and runtime_present:
            conclusion = (
                "没有扫描到控制配置，无法判断配置层；运行时仍开着"
                if runtime_on
                else "没有扫描到控制配置，无法判断配置层；运行时已是「关」"
            )
        elif not config_present and not runtime_present:
            conclusion = "该 SDK 构建未暴露此开关，无法也不需要设置"
        elif not config_present and runtime_present:
            # 配置里没有这个键，但运行时日志里带出来了：大概率是引擎编译期默认值，只能等日志刷新
            conclusion = (
                "配置里没有这个键，属于引擎编译期默认值；重进语音场景后再看，若仍是「开」则该值被写死在客户端"
                if runtime_on
                else "配置里没有这个键，但运行时已经是「关」"
            )
        elif config_on and runtime_on:
            conclusion = "配置与运行时都还开着，先执行一次「关闭全部音频处理」"
        elif config_on:
            conclusion = "配置里仍开着，执行一次「关闭全部音频处理」"
        elif runtime_on:
            conclusion = "配置已关，运行时仍是旧值 —— 重进一次游戏语音场景刷新"
        else:
            conclusion = "已关闭"

        rows.append(
            (
                [audio_off.label(key), config_text, runtime_text, conclusion],
                tone_for(key),
            )
        )

    # 丢包保护属于「保留项」，单独一行说明
    fec_info = config_state.get("anti_dropout") or {}
    if fec_info.get("present"):
        rows.append(
            (
                [
                    audio_off.label("anti_dropout"),
                    "关" if fec_info.get("all_off") else "开",
                    cell(runtime_state, "anti_dropout"),
                    "丢包保护不是音频处理，保持开启可减少断音",
                ],
                "muted",
            )
        )
    return rows

def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def rate_text(value: int | None) -> str:
    if value is None:
        return "未知"
    return f"{value // 1000} kHz" if value % 1000 == 0 else f"{value} Hz"


def bitrate_text(value: int | None) -> str:
    if value is None:
        return "未知"
    return f"{value // 1000} kbps" if value % 1000 == 0 else f"{value} bps"


def channel_text(value: int | None) -> str:
    return {1: "单声道", 2: "双声道"}.get(value, f"{value} 声道" if value else "未知")


def switch_text(value: int | None) -> str:
    return {0: "关", 1: "开"}.get(value, "未知" if value is None else f"值 {value}")
