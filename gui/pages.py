"""六个功能页面。

约定：页面只通过 ``ctx`` 拿引擎和任务运行器，不直接 import 上游模块。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import core, widgets
from .core import PARAM_LABELS, TOGGLE_KEYS, GmeEngine, Layout, TaskRunner
from .widgets import (
    Card,
    Chip,
    Divider,
    KeyValue,
    LogView,
    Metric,
    ScrollPage,
    button_row,
    ghost_button,
    mono_font,
    primary_button,
    table_columns,
)

DEFAULT_PARAMS = {
    "aec": 0,
    "agc": 0,
    "ans": 0,
    "ains": 0,
    "vad": 0,
    "fec": 1,
    "frame": 40,
    "sample_rate": 48000,
    "channel": 2,
    "codec_prof": 4129,
    "kbps": 128,
    "bitrate": 128000,
    "jitter_init": 1000,
    "jitter_min": 1200,
    "jitter_max": 2000,
}

PRESETS: dict[str, dict[str, Any]] = {
    "全部处理关闭": {
        "name": "全部处理关闭",
        "description": "关闭全部音频处理（AEC/AGC/ANS/AINS/VAD/DTX/静音检测），48 kHz 双声道 128 kbps，保留丢包保护",
        "audio": DEFAULT_PARAMS,
    },
    "上游默认（虚拟麦克风音乐）": {
        "name": "虚拟麦克风音乐参数",
        "description": "面向本机音乐/虚拟声卡输入，关闭全部语音处理",
        "audio": DEFAULT_PARAMS,
    },
    "通话优先（单声道低码率）": {
        "name": "通话优先参数",
        "description": "面向纯人声通话，保留常规采样率与单声道，仅关闭 AEC/AGC/降噪",
        "audio": {**DEFAULT_PARAMS, "sample_rate": 16000, "channel": 1, "kbps": 32, "bitrate": 32000, "frame": 20},
    },
    "低延迟（缓冲收紧）": {
        "name": "低延迟参数",
        "description": "在音乐方案基础上收紧 jitter 缓冲，换取更低延迟",
        "audio": {**DEFAULT_PARAMS, "jitter_init": 200, "jitter_min": 200, "jitter_max": 600},
    },
    "保守（只关 AI 降噪）": {
        "name": "保守参数",
        "description": "保留常规处理链路，仅关闭 AI 降噪并提升码率",
        "audio": {**DEFAULT_PARAMS, "aec": 1, "agc": 1, "ans": 1, "vad": 1, "kbps": 64, "bitrate": 64000},
    },
}

RUNTIME_LABELS = {
    "matched": "游戏已使用当前方案",
    "matched_config_current": "游戏已使用当前方案（本地配置一致）",
    "not_matched": "游戏还未切换到当前方案",
    "stale_matched": "最近记录已匹配，进入语音场景可再确认",
    "stale_not_matched": "最近记录未匹配，请进入语音场景刷新",
    "no_sample": "还没有语音参数记录",
    "no_log": "还没有游戏语音记录",
}


def val(mapping: Any, *path: str, default: Any = None) -> Any:
    current = mapping
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def rich_label(text: str = "") -> QLabel:
    """可选中文本的富文本标签。"""

    label = QLabel(text)
    label.setTextFormat(Qt.RichText)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def stat_row(label: str, value: str, tone: str = "") -> str:
    color = widgets.LEVEL_COLORS.get(tone, widgets.TEXT)
    return (
        f"<span style='color:{widgets.TEXT_DIM}'>{label}</span> &nbsp;"
        f"<span style='color:{color}'>{value}</span>"
    )


def copyable_line(text: str) -> QLineEdit:
    line = QLineEdit(text)
    line.setReadOnly(True)
    line.setCursorPosition(0)
    return line


@dataclass
class AppContext:
    """页面需要的全部依赖。"""

    layout: Layout
    engine: GmeEngine
    tasks: TaskRunner
    log: Callable[[str, str], None]
    go_to: Callable[[str], None]
    refresh_status: Callable[[bool], None]
    refresh_params: Callable[[], None]
    request_inject: Callable[[], None]
    request_restore: Callable[[], None]
    request_rollback: Callable[[str], None]
    refresh_advanced: Callable[[], None]
    refresh_backups: Callable[[], None]
    refresh_audio_off: Callable[[], None]
    request_audio_off: Callable[[], None]
    request_preset: Callable[[str], None]
    action_log_view: Callable[[], LogView]
    is_admin: Callable[[], bool]

    # 由外壳在每次 status 刷新后填充，页面只读
    processing_status: dict[str, Any] = field(default_factory=dict)


class DetailTable(QTableWidget):
    """只读明细表：不滚动、按内容撑高，适合放在卡片里。"""

    MAX_HEIGHT = 420

    def __init__(self, headers: list[str], parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
        table_columns(self, headers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.verticalHeader().setDefaultSectionSize(30)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)

    def fill(self, rows: list[list[Any]], tones: list[dict[int, str]] | None = None) -> None:
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem("—" if value is None else str(value))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if tones and r < len(tones) and c in tones[r]:
                    item.setForeground(QColor(widgets.LEVEL_COLORS.get(tones[r][c], widgets.TEXT)))
                self.setItem(r, c, item)
        self.resizeRowsToContents()
        height = self.horizontalHeader().height() + 4
        for r in range(self.rowCount()):
            height += self.rowHeight(r)
        self.setFixedHeight(min(max(height, 44), self.MAX_HEIGHT))


# --------------------------------------------------------------------------- #
# 1. 总览
# --------------------------------------------------------------------------- #

class DashboardPage(ScrollPage):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.add_page_title("总览", "一眼看清当前语音参数、生效状态与风险项")

        # ---- 状态条 ---- #
        hero = Card("当前生效状态")
        hero_row = QHBoxLayout()
        hero_row.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(6)
        self.hero_chip = Chip("读取中 …", "muted")
        self.hero_message = QLabel("正在读取 GME 配置与运行日志 …")
        self.hero_message.setWordWrap(True)
        self.hero_message.setObjectName("Muted")
        left.addWidget(self.hero_chip, 0, Qt.AlignLeft)
        left.addWidget(self.hero_message)
        hero_row.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.hero_hosts = rich_label(stat_row("联网配置", "读取中"))
        self.hero_configs = rich_label(stat_row("本地配置", "读取中"))
        self.hero_log = rich_label(stat_row("运行日志", "读取中"))
        for widget in (self.hero_hosts, self.hero_configs, self.hero_log):
            right.addWidget(widget)
        hero_row.addLayout(right, 2)
        hero.add_layout(hero_row)

        hero.add(Divider())
        self.hero_next = QLabel("下一步：—")
        self.hero_next.setWordWrap(True)
        self.hero_next.setObjectName("Faint")
        hero.add(self.hero_next)

        hero.add_layout(
            button_row(
                primary_button("重新注入（需管理员）", lambda: self.ctx.request_inject()),
                ghost_button("刷新状态", lambda: self.ctx.refresh_status(True)),
                ghost_button("查看运行日志", lambda: self.ctx.go_to("logs")),
                ghost_button("编辑参数方案", lambda: self.ctx.go_to("params")),
            )
        )
        self.add(hero)

        # ---- 指标 ---- #
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.metric_state = Metric("生效判定", "读取中")
        self.metric_quality = Metric("游戏当前音质", "—")
        self.metric_processing = Metric("音频处理", "—")
        self.metric_target = Metric("目标方案", "—")
        for metric in (self.metric_state, self.metric_quality, self.metric_processing, self.metric_target):
            metrics.addWidget(metric, 1)
        holder = QWidget()
        holder.setLayout(metrics)
        self.add(holder)

        # ---- 游戏自带音频处理（全部关闭） ---- #
        self.proc_card = Card(
            "游戏自带音频处理",
            "目标：全部关闭。配置层来自解码后的 gmesdk_control_*.config，运行层来自 GMESDK 日志",
        )
        self.proc_chip = Chip("读取中", "muted")
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addWidget(self.proc_chip)
        chip_row.addStretch(1)
        self.proc_fix_button = primary_button("关闭全部音频处理", lambda: self.ctx.request_audio_off())
        self.proc_fix_button.setToolTip(
            "把所有 profile 的 AEC / AGC / ANS / AINS / VAD / DTX / silence_detect 全部写 0，"
            "并同步写入 av_config.json。需要管理员权限；不改 hosts。"
        )
        chip_row.addWidget(ghost_button("刷新", lambda: self.ctx.refresh_audio_off()))
        chip_row.addWidget(self.proc_fix_button)
        self.proc_card.add_layout(chip_row)

        self.proc_table = DetailTable(["处理项", "配置层", "游戏运行时", "结论"])
        self.proc_card.add(self.proc_table)
        self.proc_hint = QLabel("")
        self.proc_hint.setObjectName("Faint")
        self.proc_hint.setWordWrap(True)
        self.proc_card.add(self.proc_hint)
        self.add(self.proc_card)

        # ---- 对比表 ---- #
        self.compare_card = Card("目标参数 vs 游戏实际参数", "游戏实际数值取自 GMESDK 运行日志的最新记录")
        self.compare_table = DetailTable(["参数", "目标值", "游戏当前值", "结论"])
        self.compare_card.add(self.compare_table)
        self.add(self.compare_card)

        # ---- 诊断 ---- #
        self.diag_card = Card("诊断与建议")
        self.diag_body = QVBoxLayout()
        self.diag_body.setSpacing(6)
        self.diag_card.add_layout(self.diag_body)
        self.add(self.diag_card)

        # ---- 路径 ---- #
        paths_card = Card("关键路径")
        self.kv_params = KeyValue("参数文件", "—", mono=True)
        self.kv_settings = KeyValue("设置文件", "—", mono=True)
        self.kv_gme = KeyValue("GME 数据目录", "—", mono=True)
        self.kv_game = KeyValue("游戏目录", "—", mono=True)
        self.kv_log = KeyValue("最新日志", "—", mono=True)
        for widget in (self.kv_params, self.kv_settings, self.kv_gme, self.kv_game, self.kv_log):
            paths_card.add(widget)
        paths_card.add_layout(
            button_row(
                ghost_button("打开 GME 数据目录", self.open_gme_dir),
                ghost_button("打开项目目录", lambda: core.reveal_in_explorer(self.ctx.layout.core_dir)),
            )
        )
        self.add(paths_card)
        self.add_stretch()

        self.diagnosis: dict[str, Any] = {}
        self.runtime: dict[str, Any] = {}
        self._shown_once = False
        self.set_profile({})
        self.set_status(None)

    # ---- 动作 ---- #

    def open_gme_dir(self) -> None:
        try:
            path = Path(self.ctx.engine._mod("paths").gme_dir())
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"定位 GME 目录失败：{exc}", "error")
            return
        core.reveal_in_explorer(path)

    def on_shown(self) -> None:
        # 启动时 shell 已经拉过一次状态，别在首屏再来一遍
        if getattr(self, "_shown_once", False):
            self.ctx.refresh_status(False)
        self._shown_once = True

    # ---- 数据填充 ---- #

    def set_profile(self, profile: dict[str, Any]) -> None:
        target = profile.get("target") or {}
        self.metric_target.set_value(profile.get("name") or "—")
        self.metric_quality.set_value(
            f"{core.rate_text(target.get('sample_rate'))} / {core.channel_text(target.get('channel'))}"
        )
        all_off = all(target.get(key) == 0 for key in TOGGLE_KEYS[:5])
        self.metric_processing.set_value("全部关闭" if all_off else "部分开启", "ok" if all_off else "warn")
        self.kv_params.set_value(str(profile.get("path") or self.ctx.layout.audio_params))

    def set_status(self, status: dict[str, Any] | None) -> None:
        engine = self.ctx.engine
        self.kv_settings.set_value(str(self.ctx.layout.settings))
        try:
            gme_dir = str(engine._mod("paths").gme_dir())
        except Exception:  # noqa: BLE001
            gme_dir = "—"
        try:
            game_dir = engine._mod("paths").game_dir()
        except Exception:  # noqa: BLE001
            game_dir = None
        self.kv_gme.set_value(gme_dir)
        self.kv_game.set_value(str(game_dir) if game_dir else "未检测到（游戏未运行或未配置）")

        if status is None:
            self.hero_chip.set_tone("muted", "读取中 …")
            self.hero_message.setText("正在读取 GME 配置与运行日志 …")
            self.metric_state.set_value("读取中")
            self.compare_table.fill([["读取中", "—", "—", "—"]])
            return

        runtime = status.get("runtime") or {}
        diagnosis = status.get("diagnosis") or {}
        hosts = status.get("hosts") or {}
        self.diagnosis = diagnosis
        self.runtime = runtime

        effective = bool(status.get("effective"))
        code = diagnosis.get("code") or "unknown"
        if effective:
            self.hero_chip.set_tone("ok", "已生效")
        elif code in {"runtime_override", "runtime_mismatch", "stale_log"}:
            self.hero_chip.set_tone("warn", "待确认")
        else:
            self.hero_chip.set_tone("muted", "未完成")

        self.hero_message.setText(diagnosis.get("message") or "还没有足够的游戏记录可确认结果。")
        self.metric_state.set_value("已生效" if effective else "待确认", "ok" if effective else "warn")

        self.hero_hosts.setText(
            stat_row("联网配置", "已锁定" if hosts.get("blocked") else "未锁定", "ok" if hosts.get("blocked") else "warn")
        )
        self.hero_configs.setText(
            stat_row(
                "本地配置",
                "已写入" if status.get("configs_match_target") else "待确认",
                "ok" if status.get("configs_match_target") else "warn",
            )
        )
        log_path = runtime.get("log")
        if log_path:
            last = (runtime.get("log_last_write") or "").replace("T", " ")
            self.hero_log.setText(stat_row("运行日志", f"{Path(log_path).name}（{last}）"))
            self.kv_log.set_value(str(log_path))
        else:
            self.hero_log.setText(stat_row("运行日志", "尚未生成 GME 日志", "warn"))

        runtime_status = runtime.get("runtime_status") or "no_log"
        next_text = f"游戏记录：{RUNTIME_LABELS.get(runtime_status, runtime_status)}"
        if runtime.get("target_sample_time"):
            next_text += f"　|　记录时间：{runtime['target_sample_time']}"
        self.hero_next.setText(next_text)

        sample = runtime.get("target_sample") or {}
        if sample:
            self.metric_quality.set_value(
                f"{core.rate_text(sample.get('sr'))} / {core.channel_text(sample.get('ch'))}"
            )
            enabled = [
                label
                for label, key in (("回声消除", "aec"), ("自动音量", "agc"), ("降噪", "ans"), ("AI 降噪", "ains"), ("静音检测", "vad"))
                if sample.get(key)
            ]
            self.metric_processing.set_value(
                "全部关闭" if not enabled else f"{len(enabled)} 项开启", "ok" if not enabled else "warn"
            )

        self._fill_compare(status)
        self._fill_processing()
        self._fill_diagnosis(status, effective)

    def _fill_processing(self) -> None:
        status = self.ctx.processing_status or {}
        rows = core.processing_table_rows(status) if status else []
        if not rows:
            self.proc_chip.set_tone("muted", "暂无数据")
            self.proc_table.fill([["读取中", "—", "—", "—"]])
            self.proc_hint.setText("")
            return

        config_state = status.get("config_state") or {}
        runtime_state = status.get("runtime_state") or {}
        from . import audio_off

        config_on = audio_off.enabled_keys(config_state)
        runtime_on = audio_off.enabled_keys(runtime_state)
        files = status.get("config_files") or []
        profiles = status.get("config_profiles") or []
        has_runtime = bool(status.get("runtime_sample"))

        if not profiles and not has_runtime:
            # 既没有控制配置、也没有运行日志：这时候说「全部关闭」是误导
            self.proc_chip.set_tone("muted", "无数据")
        elif not config_on and not runtime_on:
            self.proc_chip.set_tone("ok", "全部关闭")
        elif config_on:
            self.proc_chip.set_tone("warn", f"配置里还有 {len(config_on)} 项开着")
        else:
            self.proc_chip.set_tone("warn", "运行层还有处理未刷新")

        tones = [{1: tone, 2: tone, 3: tone} for _, tone in rows]
        self.proc_table.fill([cells for cells, _ in rows], tones)

        hints: list[str] = []
        hints.append(f"扫描到 {len(files)} 个控制配置文件：" + ("、".join(files) if files else "无"))
        if config_on:
            hints.append(
                "配置层仍开着：" + "、".join(audio_off.label(key) for key in config_on)
                + "　→ 点「关闭全部音频处理」（需管理员）"
            )
        if runtime_on:
            hints.append(
                "游戏运行时仍开着：" + "、".join(audio_off.label(key) for key in runtime_on)
                + "　→ 关掉后要重进一次游戏语音场景，日志才会刷新"
            )
        absent = audio_off.missing_keys(config_state)
        if absent:
            hints.append(f"本机 SDK 构建里没有这些键（写了也不生效）：{'、'.join(absent)}")
        if not self.ctx.is_admin():
            hints.append("当前不是管理员：点按钮会先弹 UAC 提权窗口。")
        self.proc_hint.setText("\n".join(hints))

    def _fill_compare(self, status: dict[str, Any]) -> None:
        runtime = status.get("runtime") or {}
        sample = runtime.get("target_sample") or {}
        expected = runtime.get("expected") or {}
        if not sample:
            self.compare_table.fill([["—", "—", "—", "日志中还没有语音参数记录"]])
            self.compare_card.set_subtitle("日志中还没有 PrepareEncParam / SetAudParam 记录，先进一次游戏语音场景")
            return
        self.compare_card.set_subtitle(
            f"游戏记录时间：{runtime.get('target_sample_time') or '未知'}　|　"
            f"配置修改时间：{runtime.get('latest_config_time') or '未知'}"
            + ("" if runtime.get("verification_valid") else "　（日志早于配置修改，需要刷新）")
        )

        rows: list[list[Any]] = []
        tones: list[dict[int, str]] = []

        pairs = [
            ("采样率", core.rate_text(expected.get("sample_rate")), core.rate_text(sample.get("sr")), expected.get("sample_rate") == sample.get("sr")),
            ("声道", core.channel_text(expected.get("channel")), core.channel_text(sample.get("ch")), expected.get("channel") == sample.get("ch")),
            ("码率", core.bitrate_text(expected.get("bitrate")), core.bitrate_text(sample.get("br")), (sample.get("br") or 0) >= (expected.get("bitrate") or 0)),
            ("帧长", f"{expected.get('frame')} ms", f"{sample.get('frame')} ms", expected.get("frame") == sample.get("frame")),
            ("编码模式", expected.get("codec_prof"), sample.get("codec"), expected.get("codec_prof") == sample.get("codec")),
            ("回声消除 AEC", core.switch_text(expected.get("aec")), core.switch_text(sample.get("aec")), expected.get("aec") == sample.get("aec")),
            ("自动音量 AGC", core.switch_text(expected.get("agc")), core.switch_text(sample.get("agc")), expected.get("agc") == sample.get("agc")),
            ("普通降噪 ANS", core.switch_text(expected.get("ans")), core.switch_text(sample.get("ans")), expected.get("ans") == sample.get("ans")),
            ("AI 降噪 AINS", core.switch_text(expected.get("ains")), core.switch_text(sample.get("ains")), expected.get("ains") == sample.get("ains")),
            ("静音检测 VAD", core.switch_text(expected.get("vad")), core.switch_text(sample.get("vad")), expected.get("vad") == sample.get("vad")),
            ("丢包保护 FEC", core.switch_text(expected.get("fec")), core.switch_text(sample.get("fec")), expected.get("fec") == sample.get("fec")),
            ("缓冲初始", f"{expected.get('jitter_init')} ms", f"{sample.get('jitter_init')} ms", expected.get("jitter_init") == sample.get("jitter_init")),
            ("缓冲下限", f"{expected.get('jitter_min')} ms", f"{sample.get('jitter_min')} ms", expected.get("jitter_min") == sample.get("jitter_min")),
            ("缓冲上限", f"{expected.get('jitter_max')} ms", f"{sample.get('jitter_max')} ms", expected.get("jitter_max") == sample.get("jitter_max")),
        ]
        for name, target, actual, ok in pairs:
            rows.append([name, target, actual, "一致" if ok else "不一致"])
            tones.append({2: "ok" if ok else "warn", 3: "ok" if ok else "warn"})
        self.compare_table.fill(rows, tones)

    def _fill_diagnosis(self, status: dict[str, Any], effective: bool) -> None:
        while self.diag_body.count():
            item = self.diag_body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        lines: list[tuple[str, str]] = []
        diagnosis = status.get("diagnosis") or {}
        hosts = status.get("hosts") or {}
        runtime = status.get("runtime") or {}

        if diagnosis.get("code") and diagnosis.get("code") != "unknown":
            lines.append((diagnosis.get("message", ""), "info" if effective else "warn"))
        if not hosts.get("blocked"):
            lines.append(("hosts 里还没有 GME 屏蔽段，远程配置可能随时覆盖本地参数；以管理员运行一次 inject 即可锁定。", "warn"))
        if not status.get("configs_match_target"):
            lines.append(("本地配置与控制配置尚未全部匹配目标参数，需要执行一次 inject。", "warn"))
        if runtime.get("target_mismatches"):
            names = "、".join(item.get("name", "?") for item in runtime["target_mismatches"])
            lines.append((f"游戏仍在使用自己的数值：{names}。inject 后需重新进入语音场景才会刷新。", "warn"))
        if runtime.get("latest_av_control_event"):
            event = runtime["latest_av_control_event"]
            lines.append((f"最近一次远程配置请求：{event.get('event')}（日志第 {event.get('line')} 行）", "dim"))
        if not lines:
            lines.append(("没有发现明显问题，可以在游戏里测试语音或音乐输入。", "ok"))
        if not effective:
            lines.append(("提醒：inject 需要管理员权限；改完配置后要重新进一次游戏语音场景，日志才会刷新。", "dim"))

        for text, tone in lines:
            label = QLabel(f"• {text}")
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {widgets.LEVEL_COLORS.get(tone, widgets.TEXT)}; background: transparent;")
            self.diag_body.addWidget(label)

# --------------------------------------------------------------------------- #
# 2. 参数方案
# --------------------------------------------------------------------------- #

class ParamsPage(ScrollPage):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.inputs: dict[str, QWidget] = {}
        self._loading = False

        self.add_page_title("参数方案", "这里改的是 audio_params.json，也就是 inject 会写入 GME 的目标音频参数")

        head = Card("方案信息")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("方案名称")
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("用途说明")
        self.name_input.textChanged.connect(self._update_preview)
        self.desc_input.textChanged.connect(self._update_preview)
        for label, widget in (("方案名称", self.name_input), ("用途说明", self.desc_input)):
            row = QHBoxLayout()
            tag = QLabel(label)
            tag.setObjectName("Muted")
            tag.setMinimumWidth(72)
            row.addWidget(tag)
            row.addWidget(widget, 1)
            head.add_layout(row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_tag = QLabel("预设方案")
        preset_tag.setObjectName("Muted")
        preset_row.addWidget(preset_tag)
        for name in PRESETS:
            preset_row.addWidget(ghost_button(name, (lambda n=name: self.apply_preset(n))))
        preset_row.addWidget(ghost_button("从文件重新载入", self.reload))
        preset_row.addStretch(1)
        head.add_layout(preset_row)
        self.add(head)

        quality = Card("音质参数", "采样率 / 声道 / 码率决定实际传输带宽与音质")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self.combo_rate = QComboBox()
        for label, value in (
            ("48000 Hz（48 kHz）", 48000),
            ("44100 Hz", 44100),
            ("32000 Hz", 32000),
            ("24000 Hz", 24000),
            ("16000 Hz（默认通话档）", 16000),
        ):
            self.combo_rate.addItem(label, value)
        self.combo_channel = QComboBox()
        for label, value in (("双声道（2）", 2), ("单声道（1）", 1)):
            self.combo_channel.addItem(label, value)
        self.combo_codec = QComboBox()
        for label, value in (("4129（上游默认）", 4129), ("4102", 4102), ("4103", 4103), ("4128", 4128)):
            self.combo_codec.addItem(label, value)

        self.spin_frame = self._spin(10, 100, 1, " ms")
        self.spin_kbps = self._spin(8, 512, 8, " kbps")
        self.spin_bitrate = self._spin(8000, 512000, 8000, " bps")

        fields = [
            ("采样率", self.combo_rate),
            ("声道数", self.combo_channel),
            ("编码模式 codec_prof", self.combo_codec),
            ("帧长", self.spin_frame),
            ("码率 kbps", self.spin_kbps),
            ("码率 bitrate", self.spin_bitrate),
        ]
        for index, (label, widget) in enumerate(fields):
            row, col = divmod(index, 2)
            self._field(label, widget, row, col, grid)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        quality.add_layout(grid)
        self.inputs.update(
            {
                "sample_rate": self.combo_rate,
                "channel": self.combo_channel,
                "codec_prof": self.combo_codec,
                "frame": self.spin_frame,
                "kbps": self.spin_kbps,
                "bitrate": self.spin_bitrate,
            }
        )
        self.add(quality)

        processing = Card("音频处理开关", "关闭得越多链路越直通；FEC 建议保持开启")
        proc_grid = QGridLayout()
        proc_grid.setHorizontalSpacing(18)
        proc_grid.setVerticalSpacing(8)
        for index, key in enumerate(TOGGLE_KEYS):
            label, tip = PARAM_LABELS[key]
            box = QCheckBox(label)
            box.setToolTip(tip)
            box.stateChanged.connect(self._update_preview)
            self.inputs[key] = box
            proc_grid.addWidget(box, index // 3, index % 3)
        processing.add_layout(proc_grid)
        processing.add(Divider())

        hint = QLabel(
            "上面这 6 个开关决定 <code>audio_params.json</code> 的目标值。<br>"
            "但 GME 控制配置里还存在 <b>DTX</b>、<b>silence_detect</b> 这类由云端下发、"
            "上游 <code>inject</code> 覆盖不到的开关 —— 要真正「全部关掉」，"
            "用下面的按钮逐个 profile 归零。"
        )
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        hint.setObjectName("Faint")
        processing.add(hint)
        processing.add_layout(
            button_row(
                primary_button("关闭全部游戏内音频处理", lambda: self.ctx.request_audio_off()),
                ghost_button("去总览看逐项核验", lambda: self.ctx.go_to("dashboard")),
                ghost_button("套用「全部处理关闭」预设", lambda: self.apply_preset("全部处理关闭")),
            )
        )
        self.add(processing)

        buffer_card = Card("网络缓冲（jitter）", "缓冲越大越抗抖动，延迟也越高")
        buf_grid = QGridLayout()
        buf_grid.setHorizontalSpacing(14)
        buf_grid.setVerticalSpacing(10)
        self.spin_jinit = self._spin(0, 5000, 50, " ms")
        self.spin_jmin = self._spin(0, 5000, 50, " ms")
        self.spin_jmax = self._spin(0, 8000, 50, " ms")
        for index, (label, widget) in enumerate(
            (("初始值 jitter_init", self.spin_jinit), ("下限 jitter_min", self.spin_jmin), ("上限 jitter_max", self.spin_jmax))
        ):
            self._field(label, widget, 0, index, buf_grid)
        buffer_card.add_layout(buf_grid)
        self.inputs.update({"jitter_init": self.spin_jinit, "jitter_min": self.spin_jmin, "jitter_max": self.spin_jmax})
        self.add(buffer_card)

        preview = Card("校验与预览", "保存前按上游规则校验；保存后还需要 inject 才会写进 GME 配置")
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.status_chip = Chip("未校验", "muted")
        chip_row.addWidget(self.status_chip)
        chip_row.addStretch(1)
        chip_row.addWidget(ghost_button("校验", self.validate))
        chip_row.addWidget(ghost_button("恢复上游默认值", self.restore_defaults))
        chip_row.addWidget(primary_button("保存到 audio_params.json", self.save))
        preview.add_layout(chip_row)

        self.json_view = QPlainTextEdit()
        self.json_view.setFont(mono_font(9))
        self.json_view.setMinimumHeight(200)
        preview.add(self.json_view)
        preview.add_layout(
            button_row(
                ghost_button("用文本覆盖表单（高级）", self.apply_from_text),
                ghost_button("重新载入文件", self.reload),
                ghost_button("打开项目目录", lambda: core.reveal_in_explorer(self.ctx.layout.core_dir)),
            )
        )
        self.add(preview)
        self.add_stretch()

        for widget in list(self.inputs.values()):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._update_preview)
                if widget.isEditable():
                    widget.editTextChanged.connect(self._update_preview)
        self.spin_kbps.editTextChanged.connect(lambda _=None: self._sync_bitrate())

        self.reload()

    @staticmethod
    def _field(label: str, widget: QWidget, row: int, col: int, grid: QGridLayout) -> None:
        """把「标签 + 控件」放进网格的一个格子。"""

        tag = QLabel(label)
        tag.setObjectName("Muted")
        holder = QVBoxLayout()
        holder.setSpacing(4)
        holder.addWidget(tag)
        holder.addWidget(widget)
        grid.addLayout(holder, row, col)

    @staticmethod
    def _spin(low: int, high: int, step: int, suffix: str) -> QComboBox:
        """数值输入：可编辑下拉框，自带校验，且不像 QSpinBox 那样有粗大的加减按钮。"""

        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setValidator(QIntValidator(low, high, combo))
        combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        combo._suffix = suffix  # type: ignore[attr-defined]
        combo._low = low  # type: ignore[attr-defined]
        combo._high = high  # type: ignore[attr-defined]
        combo._step = step  # type: ignore[attr-defined]
        return combo

    @staticmethod
    def _set_spin(combo: QComboBox, value: int) -> None:
        combo.setEditText(f"{value}{combo._suffix}")  # type: ignore[attr-defined]

    @staticmethod
    def _get_spin(combo: QComboBox) -> int:
        text = combo.currentText().strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return int(combo._low)  # type: ignore[attr-defined]
        value = int(digits)
        return max(int(combo._low), min(int(combo._high), value))  # type: ignore[attr-defined]

    def _sync_bitrate(self) -> None:
        if self._loading:
            return
        kbps = self._get_spin(self.spin_kbps)
        if self._get_spin(self.spin_bitrate) < kbps * 1000:
            self._set_spin(self.spin_bitrate, kbps * 1000)

    # ---- 表单 <-> 数据 ---- #

    def collect(self) -> dict[str, Any]:
        audio = {key: (1 if self.inputs[key].isChecked() else 0) for key in TOGGLE_KEYS}  # type: ignore[attr-defined]
        audio.update(
            {
                "frame": self._get_spin(self.spin_frame),
                "sample_rate": int(self.combo_rate.currentData()),
                "channel": int(self.combo_channel.currentData()),
                "codec_prof": int(self.combo_codec.currentData()),
                "kbps": self._get_spin(self.spin_kbps),
                "bitrate": self._get_spin(self.spin_bitrate),
                "jitter_init": self._get_spin(self.spin_jinit),
                "jitter_min": self._get_spin(self.spin_jmin),
                "jitter_max": self._get_spin(self.spin_jmax),
            }
        )
        return {
            "name": self.name_input.text().strip() or "自定义音频参数",
            "description": self.desc_input.text().strip() or "用户自定义参数",
            "audio": audio,
        }

    def load_into_form(self, payload: dict[str, Any]) -> None:
        """把 payload 填进表单。

        对畸形数据要宽容：键缺失、值为 null、值不是整数时退回默认值并在预览里标注，
        绝不能让 int(None) 之类的异常穿透到 UI 线程。
        """

        self._loading = True
        notes: list[str] = []
        try:
            self.name_input.setText(str(payload.get("name") or ""))
            self.desc_input.setText(str(payload.get("description") or ""))
            audio = payload.get("audio")
            if not isinstance(audio, dict):
                notes.append("audio 字段不是对象，已用默认值填充")
                audio = {}

            for key, widget in self.inputs.items():
                raw = audio.get(key, DEFAULT_PARAMS.get(key))

                # 值不合法（缺键/nul/非数字）→ 退回默认值并记一笔
                if not isinstance(raw, int) or isinstance(raw, bool):
                    if raw is not None:
                        notes.append(f"{key}={raw!r} 不是整数")
                    elif key in audio:
                        notes.append(f"{key} 是 null")
                    fallback = DEFAULT_PARAMS.get(key)
                    if not isinstance(fallback, int):
                        continue
                    raw = fallback
                    notes.append(f"{key} 已用默认值 {fallback}")

                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(raw))
                    continue

                if not isinstance(widget, QComboBox):
                    continue

                if hasattr(widget, "_suffix"):  # 数值型下拉框
                    self._set_spin(widget, raw)
                    continue

                index = widget.findData(raw)
                if index < 0:
                    widget.addItem(f"{raw}（自定义）", raw)
                    index = widget.count() - 1
                widget.setCurrentIndex(index)
        finally:
            self._loading = False

        self._update_preview()
        if notes:
            unique = list(dict.fromkeys(notes))
            self.status_chip.set_tone("warn", f"载入时有 {len(unique)} 处异常值被修正")
            self.json_view.setToolTip("\n".join(unique))
            for note in unique:
                self.ctx.log(f"载入参数时修正：{note}", "warn")

    def _update_preview(self) -> None:
        payload = self.collect()
        self.json_view.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self.status_chip.set_tone("muted", "已修改，待校验")

    # ---- 动作 ---- #

    def reload(self) -> None:
        try:
            payload = self.ctx.engine.load_params_raw()
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"读取 audio_params.json 失败：{exc}", "error")
            return
        self.load_into_form(payload)
        self.status_chip.set_tone("ok", "已载入文件内容")
        self.ctx.refresh_params()

    def apply_preset(self, name: str) -> None:
        preset = PRESETS.get(name)
        if not preset:
            return
        self.load_into_form(copy.deepcopy(preset))
        self.status_chip.set_tone("warn", f"已套用预设：{name}（记得保存）")
        self.ctx.log(f"套用预设「{name}」，尚未写入文件。", "info")

    def restore_defaults(self) -> None:
        self.load_into_form(copy.deepcopy(PRESETS["上游默认（虚拟麦克风音乐）"]))
        self.status_chip.set_tone("warn", "已恢复默认值（记得保存）")

    def validate(self) -> bool:
        payload = self.collect()
        try:
            self.ctx.engine.validate_params(payload)
        except Exception as exc:  # noqa: BLE001
            self.status_chip.set_tone("error", f"校验失败：{exc}")
            self.ctx.log(f"参数校验失败：{exc}", "error")
            return False
        self.status_chip.set_tone("ok", "校验通过")
        self.ctx.log("参数校验通过。", "ok")
        return True

    def save(self) -> None:
        if not self.validate():
            return
        payload = self.collect()
        try:
            self.ctx.engine.save_params_raw(payload)
        except Exception as exc:  # noqa: BLE001
            self.status_chip.set_tone("error", f"保存失败：{exc}")
            self.ctx.log(f"保存 audio_params.json 失败：{exc}", "error")
            return
        self.status_chip.set_tone("ok", "已保存，等待 inject 写入")
        self.ctx.log(f"已保存 audio_params.json（方案：{payload['name']}）。", "ok")
        self.ctx.refresh_params()
        self.ctx.refresh_status(False)

    def apply_from_text(self) -> None:
        try:
            payload = json.loads(self.json_view.toPlainText())
        except json.JSONDecodeError as exc:
            self.status_chip.set_tone("error", f"JSON 解析失败：{exc}")
            return
        if not isinstance(payload, dict):
            self.status_chip.set_tone("error", "顶层必须是 JSON 对象")
            return
        self.load_into_form(payload)
        self.status_chip.set_tone("warn", "已按文本内容刷新表单（尚未保存）")


# --------------------------------------------------------------------------- #
# 3. 高级配置
# --------------------------------------------------------------------------- #

class AdvancedPage(ScrollPage):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._raw_configs: list[dict[str, Any]] = []

        self.add_page_title("高级配置", "只读展示 GME 实际配置、settings.json 与 hosts 屏蔽状态")

        self.settings_card = Card("settings.json", "决定工具去哪里找 GME 数据目录和游戏目录")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.proc_input = QLineEdit()
        self.module_input = QLineEdit()
        self.gme_dir_input = QLineEdit()
        self.gme_dir_input.setPlaceholderText("留空 = %APPDATA%\\GME\\<process_name>")
        self.game_dir_input = QLineEdit()
        self.game_dir_input.setPlaceholderText("留空 = 自动从运行中的进程探测")
        for index, (label, widget) in enumerate(
            (
                ("目标进程名", self.proc_input),
                ("GME 模块名", self.module_input),
                ("GME 数据目录", self.gme_dir_input),
                ("游戏目录", self.game_dir_input),
            )
        ):
            tag = QLabel(label)
            tag.setObjectName("Muted")
            holder = QVBoxLayout()
            holder.setSpacing(4)
            holder.addWidget(tag)
            holder.addWidget(widget)
            grid.addLayout(holder, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.settings_card.add_layout(grid)
        self.settings_card.add_layout(
            button_row(
                primary_button("保存 settings.json", self.save_settings),
                ghost_button("重新载入", self.reload_settings),
                ghost_button("探测游戏目录", self.detect_game_dir),
            )
        )
        self.add(self.settings_card)

        self.control_card = Card("GME 控制配置（已解码）", "gmesdk_control_*.config 经过位移异或编码，这里是解码后的内容")
        self.control_meta = QLabel("读取中 …")
        self.control_meta.setObjectName("Muted")
        self.control_meta.setWordWrap(True)
        self.control_card.add(self.control_meta)
        self.control_table = DetailTable(
            ["type", "role", "默认", "采样率", "声道", "kbps", "codec", "frame", "AEC", "AGC", "ANS", "AINS", "VAD", "FEC", "缓冲 init/min/max"]
        )
        self.control_card.add(self.control_table)
        self.control_card.add_layout(
            button_row(
                ghost_button("刷新", lambda: self.ctx.refresh_advanced()),
                ghost_button("查看原始 JSON", self.show_raw_config),
                ghost_button("打开 GME 数据目录", self.open_gme_dir),
            )
        )
        self.add(self.control_card)

        self.av_card = Card("av_config.json 落点", "inject 会把这些文件写成本地覆盖配置并设为只读")
        self.av_table = DetailTable(["路径", "状态", "大小", "修改时间"])
        self.av_card.add(self.av_table)
        self.add(self.av_card)

        self.hosts_card = Card("hosts 屏蔽段", "屏蔽 GME 远程配置域名，防止本地参数被云端策略覆盖")
        self.hosts_chip = Chip("读取中", "muted")
        chip_holder = QHBoxLayout()
        chip_holder.addWidget(self.hosts_chip)
        chip_holder.addStretch(1)
        self.hosts_card.add_layout(chip_holder)
        self.hosts_text = QPlainTextEdit()
        self.hosts_text.setReadOnly(True)
        self.hosts_text.setFont(mono_font(9))
        self.hosts_text.setMaximumHeight(130)
        self.hosts_card.add(self.hosts_text)
        self.hosts_card.add_layout(
            button_row(
                ghost_button("刷新", lambda: self.ctx.refresh_advanced()),
                ghost_button("打开 hosts 所在目录", lambda: core.reveal_in_explorer(self.ctx.layout.hosts_file)),
            )
        )
        self.add(self.hosts_card)
        self.add_stretch()

        self.reload_settings()

    def on_shown(self) -> None:
        self.ctx.refresh_advanced()

    # ---- settings ---- #

    def reload_settings(self) -> None:
        try:
            settings = self.ctx.engine.load_settings()
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"读取 settings.json 失败：{exc}", "error")
            return
        self.proc_input.setText(settings.get("process_name", ""))
        self.module_input.setText(settings.get("module_name", ""))
        self.gme_dir_input.setText(settings.get("gme_dir", ""))
        self.game_dir_input.setText(settings.get("game_dir", ""))

    def save_settings(self) -> None:
        payload = {
            "process_name": self.proc_input.text().strip() or "YuanShen.exe",
            "module_name": self.module_input.text().strip() or "gmesdk.dll",
            "gme_dir": self.gme_dir_input.text().strip(),
            "game_dir": self.game_dir_input.text().strip(),
        }
        try:
            self.ctx.engine.save_settings(payload)
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"保存 settings.json 失败：{exc}", "error")
            return
        self.ctx.log(f"settings.json 已保存：目标进程 {payload['process_name']}", "ok")
        self.ctx.refresh_advanced()

    def detect_game_dir(self) -> None:
        try:
            detected = self.ctx.engine._mod("paths").detect_game_dir_from_process()
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"探测游戏目录失败：{exc}", "error")
            return
        if detected:
            self.game_dir_input.setText(str(detected))
            self.ctx.log(f"探测到游戏目录：{detected}（记得保存）", "ok")
        else:
            self.ctx.log("没有探测到正在运行的目标进程，先启动游戏再试。", "warn")

    def open_gme_dir(self) -> None:
        try:
            path = Path(self.ctx.engine._mod("paths").gme_dir())
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"定位 GME 目录失败：{exc}", "error")
            return
        core.reveal_in_explorer(path)

    # ---- 控制配置 ---- #

    def set_control_configs(self, rows: list[dict[str, Any]]) -> None:
        self._raw_configs = rows
        if not rows:
            self.control_meta.setText(
                f"没有找到 gmesdk_control_*.config。目录：{self._gme_dir_text()}；游戏还没进过语音场景时属正常。"
            )
            self.control_table.fill([["—"] * 15])
            return

        first = rows[0]
        meta = (
            f"{len(rows)} 个文件　|　{first['name']}　|　{core.human_size(first['size'])}　|　"
            f"修改时间 {first['mtime']}　|　只读：{'是' if first['readonly'] else '否'}　|　sequence={first['sequence']}"
        )
        if first.get("error"):
            meta += f"　|　解码失败：{first['error']}"
        self.control_meta.setText(meta)

        table_rows: list[list[Any]] = []
        for entry in rows:
            for profile in entry.get("profiles") or []:
                if "error" in profile:
                    table_rows.append(["解码失败", profile["error"], "", "", "", "", "", "", "", "", "", "", "", "", ""])
                    continue
                table_rows.append(
                    [
                        profile.get("type"),
                        profile.get("role"),
                        profile.get("default"),
                        core.rate_text(profile.get("sr")),
                        core.channel_text(profile.get("ch")),
                        profile.get("kbps"),
                        profile.get("codec"),
                        profile.get("frame"),
                        core.switch_text(profile.get("aec")),
                        core.switch_text(profile.get("agc")),
                        core.switch_text(profile.get("ans")),
                        core.switch_text(profile.get("ains")),
                        core.switch_text(profile.get("vad")),
                        core.switch_text(profile.get("fec")),
                        f"{profile.get('jitter_init')}/{profile.get('jitter_min')}/{profile.get('jitter_max')}",
                    ]
                )
        self.control_table.fill(table_rows or [["—"] * 15])

    def _gme_dir_text(self) -> str:
        try:
            return str(self.ctx.engine._mod("paths").gme_dir())
        except Exception:  # noqa: BLE001
            return "未知"

    def show_raw_config(self) -> None:
        if not self._raw_configs:
            self.ctx.log("还没有可展示的控制配置。", "warn")
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("控制配置原始内容")
        dialog.setIcon(QMessageBox.Information)
        dialog.setText(f"共 {len(self._raw_configs)} 个控制配置文件。点「Show Details」查看解码后的 JSON。")
        text = json.dumps(self._raw_configs, ensure_ascii=False, indent=2)
        dialog.setDetailedText(text[:20000] + ("\n…（已截断）" if len(text) > 20000 else ""))
        dialog.exec()

    def set_av_configs(self, rows: list[dict[str, Any]]) -> None:
        table_rows = []
        tones: list[dict[int, str]] = []
        for row in rows:
            table_rows.append(
                [
                    row["path"],
                    "已写入" if row["exists"] else "不存在",
                    core.human_size(row["size"]) if row["exists"] else "—",
                    row["mtime"] or "—",
                ]
            )
            tones.append({1: "ok" if row["exists"] else "muted"})
        self.av_table.fill(table_rows, tones)

    def set_hosts(self, info: dict[str, Any]) -> None:
        installed = bool(info.get("installed"))
        self.hosts_chip.set_tone("ok" if installed else "warn", "已屏蔽" if installed else "未屏蔽")
        block = info.get("block") or ""
        self.hosts_text.setPlainText(
            block
            or f"hosts 中没有屏蔽段。\n目标域名：{', '.join(info.get('blocked_hosts') or [])}\n文件：{info.get('path')}"
        )


# --------------------------------------------------------------------------- #
# 4. 备份与回滚
# --------------------------------------------------------------------------- #

class BackupsPage(ScrollPage):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._rows: list[dict[str, Any]] = []

        self.add_page_title("备份与回滚", "inject 改写任何文件前都会先复制到 backups/，这里可以手动回滚")

        warn = Card("为什么需要手动回滚", "上游的 restore 只删 hosts 屏蔽段和本工具写入的 av_config.json")
        text = QLabel(
            "被改写的 gmesdk_control_*.config 不会由 restore 自动还原，必须用这里备份的原始文件覆盖回去。\n"
            "回滚流程：① 先执行一次 restore（清掉 hosts 屏蔽段与 av_config.json）→ ② 在下面找到对应 .bak → ③ 点「回滚此文件」。\n"
            "注意：控制配置是 GME 云端下发后缓存在本地的产物，用旧备份覆盖可能与当前游戏版本不匹配；回滚后建议重进游戏让它重新生成。"
        )
        text.setWordWrap(True)
        text.setObjectName("Faint")
        warn.add(text)
        self.add(warn)

        card = Card("备份文件", "按修改时间倒序；只读控制配置会在回滚时自动去掉只读属性")
        self.table = DetailTable(["文件", "类型", "大小", "备份时间", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.StrongFocus)
        card.add(self.table)
        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("Faint")
        self.empty_hint.setWordWrap(True)
        card.add(self.empty_hint)
        card.add_layout(
            button_row(
                ghost_button("刷新列表", lambda: self.ctx.refresh_backups()),
                ghost_button("打开 backups 目录", self.open_backups),
                primary_button("回滚选中文件", self.rollback_selected),
            )
        )
        self.add(card)
        self.add_stretch()

    def on_shown(self) -> None:
        self.ctx.refresh_backups()

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        table_rows = [
            [row["name"], row["kind"], core.human_size(row["size"]), row["mtime"], "回滚此文件"] for row in rows
        ]
        self.table.fill(table_rows or [["还没有备份文件", "—", "—", "—", "—"]])
        self.empty_hint.setText(
            "" if rows else "backups/ 目前是空的：说明还没成功执行过 inject，或者备份已经被清理。"
        )

    def open_backups(self) -> None:
        self.ctx.layout.backup_dir.mkdir(parents=True, exist_ok=True)
        core.reveal_in_explorer(self.ctx.layout.backup_dir)

    def rollback_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            self.ctx.log("请先在上表里选中一个备份文件。", "warn")
            return
        entry = self._rows[row]
        confirm = QMessageBox(self)
        confirm.setWindowTitle("确认回滚")
        confirm.setIcon(QMessageBox.Warning)
        confirm.setText(f"要用备份覆盖当前文件吗？\n\n备份：{entry['name']}\n时间：{entry['mtime']}")
        confirm.setInformativeText(
            "回滚会写回 GME 数据目录或 hosts，需要管理员权限。\n"
            "如果备份与当前游戏版本不匹配，可能导致语音异常——请确认这是你想要的那份。"
        )
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.setDefaultButton(QMessageBox.No)
        if confirm.exec() != QMessageBox.Yes:
            return
        self.ctx.request_rollback(entry["path"])


# --------------------------------------------------------------------------- #
# 5. 日志与输出
# --------------------------------------------------------------------------- #

class LogsPage(ScrollPage):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._log_path: Path | None = None
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(5000)
        self._follow_timer.timeout.connect(lambda: self.reload_log(silent=True))

        self.add_page_title("日志与输出", "上半部分读游戏运行时日志，下半部分是本工具的操作记录")

        runtime = Card("GMESDK 运行日志", "status 的判定依据就是这里的 PrepareEncParam / SetAudParam 记录")
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.path_label = QLabel("—")
        self.path_label.setObjectName("Mono")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        controls.addWidget(self.path_label, 1)

        self.spin_lines = QComboBox()
        self.spin_lines.setEditable(True)
        self.spin_lines.setInsertPolicy(QComboBox.NoInsert)
        self.spin_lines.setValidator(QIntValidator(50, 5000, self.spin_lines))
        self.spin_lines.setEditText("400 行")
        self.spin_lines.setToolTip("读取运行日志的最后多少行")
        self.spin_lines.setMaximumWidth(120)
        controls.addWidget(self.spin_lines)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("关键字过滤，如 AudParam")
        self.filter_input.returnPressed.connect(lambda: self.reload_log())
        self.filter_input.setMaximumWidth(220)
        controls.addWidget(self.filter_input)

        self.follow_box = QCheckBox("自动刷新")
        self.follow_box.stateChanged.connect(self._toggle_follow)
        controls.addWidget(self.follow_box)
        runtime.add_layout(controls)

        runtime.add_layout(
            button_row(
                primary_button("读取日志", lambda: self.reload_log()),
                ghost_button("打开日志目录", self.open_log_dir),
                ghost_button("复制全部", self.copy_log),
            )
        )
        self.runtime_view = QPlainTextEdit()
        self.runtime_view.setReadOnly(True)
        self.runtime_view.setFont(mono_font(8))
        self.runtime_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.runtime_view.setMinimumHeight(320)
        runtime.add(self.runtime_view)
        self.add(runtime)

        actions = Card("工具操作输出", "GUI 与上游 CLI 的完整输出都在这里")
        actions.add(self.ctx.action_log_view())
        self.add(actions)

        self.add_stretch()

    def on_shown(self) -> None:
        self.reload_log(silent=True)

    def _toggle_follow(self, state: int) -> None:
        if state:
            self._follow_timer.start()
            self.reload_log(silent=True)
        else:
            self._follow_timer.stop()

    def open_log_dir(self) -> None:
        try:
            path = Path(self.ctx.engine._mod("paths").gme_dir())
        except Exception as exc:  # noqa: BLE001
            self.ctx.log(f"定位日志目录失败：{exc}", "error")
            return
        core.reveal_in_explorer(path)

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.runtime_view.toPlainText())
        self.ctx.log("运行日志内容已复制到剪贴板。", "dim")

    def reload_log(self, silent: bool = False) -> None:
        text = self.spin_lines.currentText().strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        limit = max(50, min(5000, int(digits))) if digits else 400
        try:
            path, lines = self.ctx.engine.tail_log(limit, self.filter_input.text())
        except Exception as exc:  # noqa: BLE001
            if not silent:
                self.ctx.log(f"读取运行日志失败：{exc}", "error")
            return
        if path is None:
            self._log_path = None
            self.path_label.setText("还没有 GMESDK 日志：进一次游戏语音场景后会自动生成")
            self.runtime_view.setPlainText("")
            if not silent:
                self.ctx.log("没有找到 GMESDK_*.log。", "warn")
            return
        self._log_path = path
        self.path_label.setText(str(path))
        self.runtime_view.setPlainText("\n".join(lines))
        cursor = self.runtime_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.runtime_view.setTextCursor(cursor)
        if not silent:
            self.ctx.log(f"已读取 {path.name} 的最后 {len(lines)} 行。", "dim")


# --------------------------------------------------------------------------- #
# 6. 帮助
# --------------------------------------------------------------------------- #

HELP_HTML = f"""
<h3 style="color:{widgets.TEXT}">这东西在干什么</h3>
<p style="color:{widgets.TEXT_DIM}">
MiliastraGME 是一个本地参数助手：它把 <code>audio_params.json</code> 里的目标音频参数写进 GME（腾讯游戏多媒体引擎）
的本地配置，同时把 GME 的远程配置域名在 hosts 里屏蔽掉，让云端下发的默认策略覆盖不了本地设置；
最后解析 <code>GMESDK_*.log</code>，确认游戏运行时真的用了这些参数。
</p>

<h3 style="color:{widgets.TEXT}">三步工作流</h3>
<table cellpadding="6">
<tr><td><b>Patch</b></td><td style="color:{widgets.TEXT_DIM}">改写 <code>gmesdk_control_*.config</code>，生成 <code>av_config.json</code></td></tr>
<tr><td><b>Lock</b></td><td style="color:{widgets.TEXT_DIM}">在 hosts 中屏蔽 gmeconf / gmeosconf.qcloud.com</td></tr>
<tr><td><b>Verify</b></td><td style="color:{widgets.TEXT_DIM}">读运行日志比对 AEC/AGC/ANS/AINS/VAD/FEC/SR/CH/BR/jitter</td></tr>
</table>

<h3 style="color:{widgets.TEXT}">命令行对照</h3>
<table cellpadding="6">
<tr><td><code>params</code></td><td style="color:{widgets.TEXT_DIM}">查看当前方案（无需管理员）→ 本界面「参数方案」页</td></tr>
<tr><td><code>status</code></td><td style="color:{widgets.TEXT_DIM}">验证是否生效（无需管理员）→ 本界面「总览」页</td></tr>
<tr><td><code>inject</code></td><td style="color:{widgets.TEXT_DIM}">写入配置 + 屏蔽远程配置（<b>需管理员</b>）→ 顶栏「注入参数」按钮</td></tr>
<tr><td><code>restore</code></td><td style="color:{widgets.TEXT_DIM}">移除注入（<b>需管理员</b>）→ 顶栏「恢复」按钮</td></tr>
<tr><td>（界面独有）</td><td style="color:{widgets.TEXT_DIM}">关闭全部音频处理、备份回滚、音频处理逐项核验 —— 上游 CLI 没有这些</td></tr>
</table>

<h3 style="color:{widgets.TEXT}">关闭全部游戏内音频处理</h3>
<p style="color:{widgets.TEXT_DIM}">
总览页有一张「游戏自带音频处理」核验表，分三层看：<b>配置层</b>（解码后的
<code>gmesdk_control_*.config</code>）、<b>游戏运行时</b>（<code>GMESDK_*.log</code> 里的
<code>PrepareEncParam</code>）、<b>结论</b>。旁边的「关闭全部音频处理」按钮会把每个 profile 的
<code>aec / agc / ans / ains / vad / dtx / silence_detect</code> 全部写 0，
并同步写 <code>av_config.json</code>；<code>anti_dropout</code>（丢包保护 FEC）会保留，它不是音频处理。
</p>
<ul style="color:{widgets.TEXT_DIM}">
<li>上游 <code>inject</code> 只覆盖 aec/agc/ans/ains/vad，<b>漏了 dtx 和 silence_detect</b>；这个按钮补上了。</li>
<li>这个按钮<b>不改 hosts</b>。要同时锁死远程配置下发，再用顶栏的 <code>inject</code>。</li>
<li>某个键在本机 SDK 构建里可能根本不存在（如本机的 ains / vad / dtx），表里会显示「—」，
  写了也不生效，属引擎编译期默认值。</li>
<li>配置改完必须<b>重进一次游戏语音场景</b>，引擎才会重新下发参数，日志才会变成「关」。</li>
</ul>

<h3 style="color:{widgets.TEXT}">生效判定怎么读</h3>
<ul style="color:{widgets.TEXT_DIM}">
<li><b>matched</b>：最新运行日志匹配目标参数 → 生效。</li>
<li><b>matched_config_current</b>：最近记录匹配，且本地配置也匹配。</li>
<li><b>not_matched</b>：日志有效，但游戏仍在用旧参数。</li>
<li><b>stale_matched / stale_not_matched</b>：日志早于本次配置修改，需要进一次语音场景刷新。</li>
<li><b>no_sample / no_log</b>：还没有可验证的语音参数记录。</li>
</ul>

<h3 style="color:{widgets.TEXT}">管理员权限怎么给</h3>
<ul style="color:{widgets.TEXT_DIM}">
<li>界面顶部会显示当前是否为管理员；不是管理员时 inject / restore / 回滚都会走 UAC 提权。</li>
<li>也可以直接双击仓库根目录的 <code>run-gui-admin.cmd</code>，它会先请求管理员再启动界面。</li>
<li>或者右键 PowerShell「以管理员身份运行」，手动执行 <code>python __main__.py inject</code>。</li>
</ul>

<h3 style="color:{widgets.WARN}">风险提示（务必读）</h3>
<ul style="color:{widgets.TEXT_DIM}">
<li>inject 会修改系统 <code>hosts</code>、GME 配置目录和可能的游戏目录文件，需要管理员权限。</li>
<li>改 hosts 属于对抗远程配置下发的行为，是否违反游戏用户协议请自行判断；上游与作者均声明不对后果负责。</li>
<li>改写后的控制配置会被设为<b>只读</b>；<code>restore</code> <b>不会</b>自动回滚它，必须去「备份与回滚」页手动还原。</li>
<li>不再使用时请执行 <code>restore</code>，并从 backups 恢复控制配置。</li>
<li>效果取决于游戏版本、GME SDK 版本、输入设备、虚拟声卡与系统音频设置，不保证一定生效。</li>
</ul>
"""


class HelpPage(ScrollPage):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.add_page_title("帮助与说明", "工具原理、命令对照、判定逻辑与风险提示")

        card = Card("说明书")
        label = QLabel(HELP_HTML)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(label)
        self.add(card)

        links = Card("项目信息")
        links.add(KeyValue("上游项目", "clearyss/MiliastraGME（GPL-3.0）", mono=True))
        links.add(KeyValue("上游说明", "docs\\UPSTREAM-README.md", mono=True))
        links.add(KeyValue("使用教程", "TUTORIAL.md", mono=True))
        links.add(KeyValue("归属声明", "NOTICE", mono=True))
        links.add(KeyValue("上游代码", "未做任何修改，界面通过 importlib 调用"))
        links.add_layout(
            button_row(
                ghost_button("打开仓库目录", lambda: core.reveal_in_explorer(self.ctx.layout.root)),
                ghost_button("打开使用教程", lambda: core.reveal_in_explorer(self.ctx.layout.root / "TUTORIAL.md")),
                ghost_button(
                    "打开上游说明",
                    lambda: core.reveal_in_explorer(self.ctx.layout.root / "docs" / "UPSTREAM-README.md"),
                ),
            )
        )
        self.add(links)
        self.add_stretch()
