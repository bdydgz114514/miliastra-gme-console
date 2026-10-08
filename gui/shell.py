"""主窗口外壳：侧边导航 + 顶部动作栏 + 操作日志。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from . import core, widgets
from .core import GmeEngine, Layout, TaskRunner
from .pages import (
    AdvancedPage,
    AppContext,
    BackupsPage,
    DashboardPage,
    HelpPage,
    LogsPage,
    ParamsPage,
)
from .widgets import Chip, LogView, ghost_button, primary_button

NAV_ITEMS = [
    ("dashboard", "总览", "状态与对比"),
    ("params", "参数方案", "改 audio_params.json"),
    ("advanced", "高级配置", "GME / settings / hosts"),
    ("backups", "备份与回滚", "手动还原"),
    ("logs", "日志与输出", "运行日志 + 操作输出"),
    ("help", "帮助与说明", "原理与风险"),
]


class MainWindow(QMainWindow):
    def __init__(self, layout: Layout, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout_info = layout
        self.setWindowTitle("MiliastraGME 控制台")
        self.resize(1240, 860)
        self.setMinimumSize(1000, 700)

        self.engine = GmeEngine(layout)
        self.tasks = TaskRunner(self)
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}

        self._build_ui()
        self._wire_tasks()

        self.log("MiliastraGME 控制台已启动。", "accent")
        self.log(f"仓库目录：{layout.root}", "dim")
        self.log(
            "当前权限：管理员" if core.is_admin() else "当前权限：普通用户（inject / restore / 回滚会走 UAC 提权）",
            "ok" if core.is_admin() else "warn",
        )
        self.refresh_params()
        self._startup_status_done = True
        self.refresh_status(False)

    # ------------------------------------------------------------------ #
    # 构建界面
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self._build_hidden_log()

        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 12, 16, 12)
        right_layout.setSpacing(12)
        right_layout.addWidget(self._build_action_bar())

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        outer.addWidget(right, 1)

        self.setCentralWidget(root)
        self._build_status_bar()

        ctx = self._make_context()
        self.ctx = ctx  # 后台任务可能在 __init__ 结束前就回报，先挂到实例上
        for key, cls in (
            ("dashboard", DashboardPage),
            ("params", ParamsPage),
            ("advanced", AdvancedPage),
            ("backups", BackupsPage),
            ("logs", LogsPage),
            ("help", HelpPage),
        ):
            page = cls(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)

        self.go_to("dashboard")

    def _make_context(self) -> AppContext:
        return AppContext(
            layout=self.layout_info,
            engine=self.engine,
            tasks=self.tasks,
            log=self.log,
            go_to=self.go_to,
            refresh_status=self.refresh_status,
            refresh_params=self.refresh_params,
            request_inject=self.request_inject,
            request_restore=self.request_restore,
            request_rollback=self.request_rollback,
            refresh_advanced=self.refresh_advanced,
            refresh_backups=self.refresh_backups,
            refresh_audio_off=self.refresh_audio_off,
            request_audio_off=self.request_audio_off,
            request_preset=self.open_preset,
            action_log_view=lambda: self.action_log,
            is_admin=core.is_admin,
        )

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setFixedWidth(212)
        sidebar.setStyleSheet(
            f"QFrame {{ background: {widgets.SURFACE}; border-right: 1px solid {widgets.BORDER}; }}"
        )
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(6)

        brand = QLabel("MiliastraGME")
        brand.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {widgets.TEXT};")
        layout.addWidget(brand)
        sub = QLabel("GME 语音参数控制台")
        sub.setStyleSheet(f"color: {widgets.TEXT_FAINT}; font-size: 11px;")
        layout.addWidget(sub)
        layout.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for key, title, hint in NAV_ITEMS:
            button = QPushButton(f"{title}\n{hint}")
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.go_to(k))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self.admin_chip = Chip("管理员" if core.is_admin() else "普通权限", "ok" if core.is_admin() else "warn")
        layout.addWidget(self.admin_chip, 0, Qt.AlignLeft)

        if not core.is_admin():
            elevate = ghost_button("以管理员身份重启界面", self.elevate_self)
            elevate.setToolTip("重新用管理员权限打开本界面，之后 inject / restore 不再弹 UAC")
            layout.addWidget(elevate)

        version = QLabel(f"上游 {self._upstream_version()}")
        version.setStyleSheet(f"color: {widgets.TEXT_FAINT}; font-size: 11px;")
        version.setWordWrap(True)
        layout.addWidget(version)
        return sidebar

    def _upstream_version(self) -> str:
        git_dir = self.layout_info.root / ".git"
        if not git_dir.exists():
            return "（无 git 信息）"
        try:
            import subprocess

            out = subprocess.run(
                ["git", "-C", str(self.layout_info.root), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=core.no_window_flags(),
            )
            return out.stdout.strip() or "（未知）"
        except Exception:  # noqa: BLE001
            return "（未知）"

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Card")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.status_chip = Chip("就绪", "muted")
        layout.addWidget(self.status_chip)

        self.headline = QLabel("正在初始化 …")
        self.headline.setObjectName("Muted")
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline, 1)

        self.refresh_button = ghost_button("刷新状态", lambda: self.refresh_status(True))
        layout.addWidget(self.refresh_button)

        self.detect_button = ghost_button("探测游戏目录", self.detect_game_dir)
        self.detect_button.setToolTip("定位游戏安装目录并写入 settings.json，让配置能覆盖到游戏侧文件")
        layout.addWidget(self.detect_button)

        self.restore_button = QPushButton("恢复（restore）")
        self.restore_button.setObjectName("Danger")
        self.restore_button.setCursor(Qt.PointingHandCursor)
        self.restore_button.setToolTip("移除 hosts 屏蔽段与本工具写入的 av_config.json；需要管理员")
        self.restore_button.clicked.connect(self.request_restore)
        layout.addWidget(self.restore_button)

        self.inject_button = primary_button("注入参数（inject）", self.request_inject)
        self.inject_button.setToolTip("把参数写进 GME 配置并锁定远程配置；需要管理员")
        layout.addWidget(self.inject_button)
        return bar

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.profile_label = QLabel("方案：读取中 …")
        self.busy_label = QLabel("")
        bar.addWidget(self.profile_label, 1)
        bar.addPermanentWidget(self.busy_label)
        self.setStatusBar(bar)

    def _build_hidden_log(self) -> None:
        self.action_log = LogView()

    # ------------------------------------------------------------------ #
    # 任务
    # ------------------------------------------------------------------ #

    def _wire_tasks(self) -> None:
        # TaskRunner.progress 是 (level, message)，self.log 的签名是 (message, level)
        self.tasks.progress.connect(lambda level, message: self.log(message, level))
        self.tasks.busy_changed.connect(self._on_busy_changed)
        self.tasks.failed.connect(self._on_task_failed)
        self.tasks.done.connect(self._on_task_done)

    def _on_busy_changed(self, busy: bool, label: str) -> None:
        self.busy_label.setText(f"运行中：{label}" if busy else "")
        self.status_chip.set_tone("info" if busy else "muted", "运行中" if busy else "就绪")
        self.inject_button.setEnabled(not busy)
        self.restore_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.detect_button.setEnabled(not busy)

    def _on_task_failed(self, name: str, message: str) -> None:
        self.log(f"任务 {name} 失败：{message}", "error")
        self.status_chip.set_tone("error", "失败")

    def _on_task_done(self, name: str, result: Any) -> None:
        if name == "params":
            self._apply_params(result)
        elif name == "status":
            self._apply_status(result)
        elif name == "inject":
            self._apply_inject(result)
        elif name == "restore":
            self._apply_restore(result)
        elif name == "advanced":
            self._apply_advanced(result)
        elif name == "audio_off":
            self._apply_audio_off(result)
        elif name == "audio_status":
            self._apply_audio_status(result)
        elif name == "detect_game":
            self._apply_detect_game(result)
        elif name == "backups":
            self.pages["backups"].set_rows(result)  # type: ignore[attr-defined]
            self.log(f"备份列表已刷新，共 {len(result)} 个文件。", "dim")
        elif name == "rollback":
            self._apply_rollback(result)

    # ------------------------------------------------------------------ #
    # 数据刷新
    # ------------------------------------------------------------------ #

    def refresh_params(self) -> None:
        def job(ctx: core.TaskContext) -> dict:
            return self.engine.audio_profile()

        self.tasks.start("params", "读取参数方案", job)

    def _apply_params(self, profile: dict) -> None:
        target = profile.get("target") or {}
        self.profile_label.setText(
            f"方案：{profile.get('name')}　|　"
            f"{core.rate_text(target.get('sample_rate'))} / {core.channel_text(target.get('channel'))} / "
            f"{core.bitrate_text(target.get('bitrate'))}"
        )
        page = self.pages.get("dashboard")
        if isinstance(page, DashboardPage):
            page.set_profile(profile)

    def refresh_status(self, verbose: bool = False) -> None:
        def job(ctx: core.TaskContext) -> dict:
            ctx.log("读取 GME 配置、hosts 与最新运行日志 …")
            return self.engine.full_status()

        if self.tasks.start("status", "读取生效状态", job) and verbose:
            self.log("开始刷新状态 …", "info")

    def _apply_status(self, status: dict) -> None:
        runtime = status.get("runtime") or {}
        diagnosis = status.get("diagnosis") or {}
        effective = bool(status.get("effective"))
        headline = diagnosis.get("message") or "还没有足够的游戏记录可确认结果。"
        self.headline.setText(headline)
        self.status_chip.set_tone("ok" if effective else "warn", "已生效" if effective else "待确认")
        self.action_log.append(
            f"[{datetime.now():%H:%M:%S}] 状态刷新：{'已生效' if effective else '待确认'}；"
            f"运行状态={runtime.get('runtime_status')}；本地配置匹配={status.get('configs_match_target')}；"
            f"hosts 屏蔽={bool((status.get('hosts') or {}).get('blocked'))}",
            "ok" if effective else "info",
        )
        page = self.pages.get("dashboard")
        if isinstance(page, DashboardPage):
            page.set_status(status)
        if not self.ctx.processing_status:
            self.refresh_audio_off()

    def refresh_advanced(self) -> None:
        def job(ctx: core.TaskContext) -> dict:
            return {
                "control": self.engine.decoded_control_configs(),
                "av": self.engine.local_av_configs(),
                "hosts": self.engine.hosts_block(),
            }

        self.tasks.start("advanced", "读取 GME 配置", job)

    def _apply_advanced(self, result: dict) -> None:
        page = self.pages.get("advanced")
        if not isinstance(page, AdvancedPage):
            return
        page.set_control_configs(result.get("control") or [])
        page.set_av_configs(result.get("av") or [])
        page.set_hosts(result.get("hosts") or {})
        page.reload_settings()
        self.log("GME 控制配置 / av_config / hosts 状态已刷新。", "dim")

    def refresh_backups(self) -> None:
        def job(ctx: core.TaskContext) -> list[dict]:
            return self.engine.list_backups()

        self.tasks.start("backups", "读取备份列表", job)

    # ------------------------------------------------------------------ #
    # 关闭全部音频处理
    # ------------------------------------------------------------------ #

    def request_audio_off(self) -> None:
        if self.tasks.busy:
            self.log("有任务正在运行，等它结束再执行。", "warn")
            return
        if not self._confirm(
            "确认关闭全部音频处理",
            "要把所有 GME profile 的音频处理开关全部关掉吗？",
            "会改写每个 profile 的：\n"
            "　AEC 回声消除、AGC 自动增益、ANS 普通降噪、\n"
            "　AINS AI 降噪、VAD 静音检测、DTX、silence_detect\n"
            "并把同样的设置写进 av_config.json（本地 + 游戏目录）。\n\n"
            "· 丢包保护 FEC(anti_dropout) 会保留，它不是音频处理\n"
            "· 本操作<b>不改 hosts</b>，远程配置仍可能下发覆盖；要锁死请另外执行 inject\n"
            "· 修改前会自动备份到 backups/\n"
            "· 需要管理员权限，未提权时会弹 UAC",
        ):
            return
        self._log_attempt("关闭全部音频处理（GUI 内置，等价于改写控制配置 + av_config）")

        if core.is_admin():
            self._run_audio_off_here()
            return
        try:
            launched = core.run_elevated(self.layout_info, "inject")
        except Exception as exc:  # noqa: BLE001
            self.log(f"提权失败：{exc}", "error")
            return
        if launched:
            self.log(
                "当前不是管理员，已改为请求提权执行上游 inject（它同样会把处理全部关掉）。",
                "warn",
            )
            self.log(
                "注意：上游 inject 还会顺带改 hosts。若想只关处理、不动 hosts，"
                "请点侧边栏「以管理员身份重启界面」后重试。",
                "warn",
            )
            self.log("提权窗口执行完后，回到本界面点「刷新状态」。", "info")
        else:
            self.log("UAC 提权被取消或以失败告终，未执行。", "error")

    def _run_audio_off_here(self) -> None:
        def job(ctx: core.TaskContext) -> dict:
            return self.engine.apply_audio_off(ctx)

        self.tasks.start("audio_off", "关闭全部音频处理", job)

    def _apply_audio_off(self, manifest: dict) -> None:
        changes = manifest.get("changes") or []
        status = manifest.get("status") or {}
        self.ctx.processing_status = status
        self._apply_audio_status(status)

        configs = manifest.get("configs") or []
        av = manifest.get("av_configs") or []
        for item in configs:
            self.log(
                f"控制配置 {Path(item['path']).name}：{'已改写' if item['changed'] else '无需改动'}"
                f"（{len(item['changes'])} 处开关归零）"
                + (f"，备份 {Path(item['backup']).name}" if item.get("backup") else ""),
                "ok" if item["changed"] else "dim",
            )
        for item in av:
            self.log(
                f"av_config {item['path']}：{'已写入' if item['changed'] else '内容一致'}",
                "ok" if item["changed"] else "dim",
            )
        self.log(
            f"共关闭 {len(changes)} 处处理开关；丢包保护 FEC 已保留。",
            "ok" if changes else "info",
        )
        if not manifest.get("game_dir"):
            self.log(
                "游戏目录未探测到，游戏安装目录下的 av_config.json 没写；启动游戏后再执行一次即可。",
                "warn",
            )
        self.log("下一步：重进一次游戏语音场景，然后点「刷新状态」确认运行层也变成「关」。", "info")
        self.refresh_params()
        self.refresh_status(True)

    def refresh_audio_off(self) -> None:
        def job(ctx: core.TaskContext) -> dict:
            return self.engine.audio_processing_status()

        self.tasks.start("audio_status", "检查音频处理状态", job)

    def _apply_audio_status(self, status: dict) -> None:
        self.ctx.processing_status = status
        from . import audio_off

        runtime_on = audio_off.enabled_keys(status.get("runtime_state") or {})
        config_on = audio_off.enabled_keys(status.get("config_state") or {})
        self.log(
            "音频处理检查：配置层 "
            + ("全部关闭" if not config_on else f"仍有 {len(config_on)} 项开着（{'、'.join(config_on)}）")
            + "；运行层 "
            + ("全部关闭" if not runtime_on else f"仍有 {len(runtime_on)} 项开着（{'、'.join(runtime_on)}）"),
            "ok" if not config_on and not runtime_on else "warn",
        )
        page = self.pages.get("dashboard")
        if isinstance(page, DashboardPage):
            page._fill_processing()

    def open_preset(self, preset: str) -> None:
        """跳到参数页并套用指定预设（不自动保存，让用户先看一眼）。"""

        self.go_to("params")
        page = self.pages.get("params")
        if isinstance(page, ParamsPage):
            page.apply_preset(preset)

    # ------------------------------------------------------------------ #
    # 游戏目录探测
    # ------------------------------------------------------------------ #

    def detect_game_dir(self) -> None:
        if self.tasks.busy:
            self.log("有任务正在运行，等它结束再探测。", "warn")
            return

        def job(ctx: core.TaskContext) -> dict:
            ctx.log("正在探测游戏目录（Win32_Process → Get-Process → MainModule 逐级回退）…")
            detected, stored = self.engine.detect_and_store_game_dir()
            return {"dir": str(detected) if detected else None, "stored": stored}

        self.tasks.start("detect_game", "探测游戏目录", job)

    def _apply_detect_game(self, result: dict) -> None:
        directory = result.get("dir")
        if not directory:
            self.log("没探测到游戏目录：游戏没在运行，或进程路径不可读。", "warn")
            self.log("可以手动指定：python gui\\app.py 启动后到「高级配置」页填「游戏目录」。", "info")
            return
        if result.get("stored"):
            self.log(f"探测到游戏目录并已写入 settings.json：{directory}", "ok")
        else:
            self.log(f"探测到游戏目录（settings.json 里已有相同值）：{directory}", "info")
        self.log("这样 inject / 关闭全部处理 时才会同时写入游戏安装目录下的 av_config.json。", "info")
        self.refresh_status(False)

    # ------------------------------------------------------------------ #
    # 注入 / 恢复 / 回滚
    # ------------------------------------------------------------------ #

    def _confirm(self, title: str, text: str, detail: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setText(text)
        box.setInformativeText(detail)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def request_inject(self) -> None:
        if self.tasks.busy:
            self.log("有任务正在运行，等它结束再注入。", "warn")
            return
        if not self._confirm(
            "确认注入参数",
            "要把当前方案写进 GME 配置吗？",
            "这会：① 改写 %APPDATA%\\GME 下的 gmesdk_control_*.config（并设为只读）\n"
            "　　　② 写入 av_config.json\n"
            "　　　③ 修改系统 hosts，屏蔽 GME 远程配置域名\n\n"
            "修改前会自动备份到 backups/。需要管理员权限，未提权时会弹出 UAC。",
        ):
            return
        self._log_attempt("inject")

        if core.is_admin():
            self._run_inject_here()
            return
        try:
            launched = core.run_elevated(self.layout_info, "inject")
        except Exception as exc:  # noqa: BLE001
            self.log(f"提权失败：{exc}", "error")
            return
        if launched:
            self.log(
                "已请求 UAC 提权，inject 会在新开的 PowerShell 窗口里执行（该窗口的输出无法回传到界面）。",
                "warn",
            )
            self.log("窗口里显示执行结束后，回到本界面点「刷新状态」即可看到结果。", "info")
        else:
            self.log("UAC 提权被取消或以失败告终，inject 未执行。", "error")

    def _run_inject_here(self) -> None:
        def job(ctx: core.TaskContext) -> dict:
            return self.engine.inject(ctx)

        self.tasks.start("inject", "写入 GME 配置", job)

    def request_restore(self) -> None:
        if self.tasks.busy:
            self.log("有任务正在运行，等它结束再恢复。", "warn")
            return
        if not self._confirm(
            "确认恢复（restore）",
            "要移除本工具做过的修改吗？",
            "这会：① 删除 hosts 中的 GME 屏蔽段　② 删除本工具写入的 av_config.json\n\n"
            "注意：被改写的 gmesdk_control_*.config 不会被自动回滚，需要之后到「备份与回滚」页手动还原。",
        ):
            return
        self._log_attempt("restore")

        if core.is_admin():
            self._run_restore_here()
            return
        try:
            launched = core.run_elevated(self.layout_info, "restore")
        except Exception as exc:  # noqa: BLE001
            self.log(f"提权失败：{exc}", "error")
            return
        if launched:
            self.log("已请求 UAC 提权，restore 会在新开的 PowerShell 窗口里执行。", "warn")
            self.log("别忘了之后去「备份与回滚」页还原 gmesdk_control_*.config。", "warn")
        else:
            self.log("UAC 提权被取消或以失败告终，restore 未执行。", "error")

    def _run_restore_here(self) -> None:
        def job(ctx: core.TaskContext) -> dict:
            return self.engine.restore(ctx)

        self.tasks.start("restore", "移除注入项", job)

    def request_rollback(self, backup_path: str) -> None:
        if self.tasks.busy:
            self.log("有任务正在运行，稍后再回滚。", "warn")
            return
        self.log(f"准备回滚：{backup_path}", "warn")

        if not core.is_admin():
            self.log(
                "回滚需要管理员权限。请从管理员 PowerShell 执行（把 <备份> 换成刚选中的文件名）：",
                "warn",
            )
            target_hint = self._guess_rollback_target(Path(backup_path))
            self.log(
                f'Copy-Item -LiteralPath "backups\\<备份>" -Destination "{target_hint}" -Force',
                "dim",
            )
            self.log("或者在顶栏点「以管理员身份重启界面」后再回来执行回滚。", "info")
            return

        def job(ctx: core.TaskContext) -> dict:
            source = Path(backup_path)
            target = self._resolve_rollback_target(source)
            if target is None:
                raise ValueError(f"无法从备份文件名推断目标路径：{source.name}")
            ctx.log(f"备份：{source}")
            ctx.log(f"目标：{target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                try:
                    target.chmod(target.stat().st_mode | 0o200)
                except Exception:  # noqa: BLE001
                    pass
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                side = target.with_name(f"{target.name}.before_rollback.{stamp}.bak")
                shutil.copy2(target, side)
                ctx.log(f"当前文件已另存：{side}")
            shutil.copy2(source, target)
            ctx.log("回滚完成。", "ok")
            return {"source": str(source), "target": str(target), "status": self.engine.full_status()}

        self.tasks.start("rollback", "回滚备份文件", job)

    def _apply_rollback(self, result: dict) -> None:
        self.log(f"已回滚：{result['source']} → {result['target']}", "ok")
        self.log("建议重进游戏让它重新生成控制配置，然后点「刷新状态」。", "info")
        self._apply_status(result["status"])
        self.refresh_advanced()
        self.refresh_backups()

    def _guess_rollback_target(self, source: Path) -> str:
        resolved = core.resolve_rollback_target(self.engine, self.layout_info, source)
        return str(resolved) if resolved else "<目标路径>"

    def _resolve_rollback_target(self, source: Path) -> Path | None:
        return core.resolve_rollback_target(self.engine, self.layout_info, source)

    # ------------------------------------------------------------------ #
    # 杂项
    # ------------------------------------------------------------------ #

    def _log_attempt(self, command: str) -> None:
        self.log(f"→ python __main__.py {command}　（等价命令，管理员 PowerShell 里可直接跑）", "dim")

    def elevate_self(self) -> None:
        if core.relaunch_self_as_admin():
            self.log("已请求提权，正在用管理员权限重启界面；确认 UAC 后可以关掉当前窗口。", "ok")
            self.close()
        else:
            self.log("提权被取消或失败。", "error")

    def log(self, message: str, level: str = "info") -> None:
        for line in str(message).splitlines() or [""]:
            self.action_log.append(f"[{datetime.now():%H:%M:%S}] {line}", level)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.log("正在退出：等待后台任务结束 …", "dim")
        self.tasks.shutdown()
        super().closeEvent(event)

    def go_to(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        shown = getattr(page, "on_shown", None)
        if callable(shown):
            shown()
