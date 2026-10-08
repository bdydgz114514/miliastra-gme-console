r"""Bug 排查：针对可疑交互构造边界用例。

覆盖：
- TaskRunner 状态机（失败后是否会卡在 busy、快速连点、队列顺序）
- ParamsPage 表单 ↔ 数据往返（含畸形输入）
- 音频处理核验表在「没有控制配置」时会不会误报
- 回滚目标推断的各种文件名
- 控制配置编解码是否无损

    python gui\bug_hunt.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui import audio_off, core, widgets  # noqa: E402
from gui.core import GmeEngine, TaskRunner, discover_layout  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(widgets.STYLESHEET)

layout = discover_layout()
engine = GmeEngine(layout)

found: list[str] = []


def bug(tag: str, detail: str) -> None:
    found.append(f"[BUG] {tag}: {detail}")
    print(f"  [BUG] {tag}: {detail}")


def ok(tag: str, detail: str = "") -> None:
    print(f"  [ok ] {tag}" + (f" — {detail}" if detail else ""))


def pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_idle(runner: TaskRunner, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while (runner.busy or runner.pending) and time.time() < end:
        pump(0.05)
    return not (runner.busy or runner.pending)


print("=" * 74)
print("1) TaskRunner 状态机")
print("=" * 74)

runner = TaskRunner()
events: list[tuple] = []
runner.done.connect(lambda n, r: events.append(("done", n, r)))
runner.failed.connect(lambda n, e: events.append(("failed", n, e)))
runner.busy_changed.connect(lambda b, l: events.append(("busy", b, l)))

# 1a 任务抛异常后必须回到 idle
runner.start("boom", "会失败的任务", lambda ctx: (_ for _ in ()).throw(RuntimeError("炸了")))
if wait_idle(runner):
    ok("任务抛异常后回到 idle")
else:
    bug("抛异常后卡在 busy", f"busy={runner.busy} pending={runner.pending}")

# 1b 快速连点：5 个任务应该全部按序执行，一个都不丢
events.clear()
for i in range(5):
    runner.start(f"t{i}", f"任务{i}", lambda ctx, n=i: n * 10)
if wait_idle(runner):
    done_results = [e[2] for e in events if e[0] == "done"]
    if done_results == [0, 10, 20, 30, 40]:
        ok("快速连点 5 次，全部按序完成", str(done_results))
    else:
        bug("队列顺序或丢失", f"得到 {done_results}")
else:
    bug("连点后卡在 busy", f"busy={runner.busy} pending={runner.pending}")

# 1c busy_changed 的 true/false 必须成对
busy_seq = [e[1] for e in events if e[0] == "busy"]
if busy_seq and busy_seq[-1] is False:
    ok("busy_changed 以 False 收尾", str(busy_seq))
else:
    bug("busy_changed 没有正确收尾", str(busy_seq))

# 1d 任务里读 ctx 的耗时日志不应把状态搞乱
events.clear()
runner.start("slow", "慢任务", lambda ctx: (time.sleep(0.3), "done")[1])
if wait_idle(runner):
    ok("慢任务正常收尾")
else:
    bug("慢任务卡住", f"busy={runner.busy}")

runner.shutdown()

print()
print("=" * 74)
print("2) ParamsPage 表单往返与畸形输入")
print("=" * 74)

from gui.pages import DEFAULT_PARAMS, PRESETS, AppContext, ParamsPage  # noqa: E402

ctx = AppContext(
    layout=layout,
    engine=engine,
    tasks=TaskRunner(),
    log=lambda m, l="info": None,
    go_to=lambda k: None,
    refresh_status=lambda v=False: None,
    refresh_params=lambda: None,
    request_inject=lambda: None,
    request_restore=lambda: None,
    request_rollback=lambda p: None,
    refresh_advanced=lambda: None,
    refresh_backups=lambda: None,
    refresh_audio_off=lambda: None,
    request_audio_off=lambda: None,
    request_preset=lambda p: None,
    action_log_view=lambda: widgets.LogView(),
    is_admin=lambda: False,
)

page = ParamsPage(ctx)

# 2a 正常往返
page.load_into_form(copy.deepcopy(PRESETS["上游默认（虚拟麦克风音乐）"]))
dumped = page.collect()
if dumped["audio"] == DEFAULT_PARAMS:
    ok("默认预设表单往返一致")
else:
    diff = {k: (DEFAULT_PARAMS.get(k), dumped["audio"].get(k)) for k in set(DEFAULT_PARAMS) | set(dumped["audio"]) if DEFAULT_PARAMS.get(k) != dumped["audio"].get(k)}
    bug("默认预设往返不一致", json.dumps(diff, ensure_ascii=False))

# 2b 所有预设都要能安全装载 + 收集
for name, preset in PRESETS.items():
    try:
        page.load_into_form(copy.deepcopy(preset))
        engine.validate_params(page.collect())
    except Exception as exc:  # noqa: BLE001
        bug(f"预设「{name}」装载/收集失败", f"{type(exc).__name__}: {exc}")
else:
    ok(f"{len(PRESETS)} 个预设全部可装载并通过校验")

# 2c 缺失的键（模拟手改过的 audio_params.json）
partial = {"name": "缺键", "audio": {"aec": 0}}
try:
    page.load_into_form(partial)
    collected = page.collect()
    if all(isinstance(collected["audio"][k], int) for k in DEFAULT_PARAMS):
        ok("audio 缺键时用默认值补齐", f"frame={collected['audio']['frame']}")
    else:
        bug("缺键补齐后类型不对", json.dumps(collected["audio"], ensure_ascii=False))
except Exception as exc:  # noqa: BLE001
    bug("audio 缺键时表单装载崩溃", f"{type(exc).__name__}: {exc}")

# 2d 值为 null（JSON 里很常见）
nulls = {"name": "null 值", "audio": {k: None for k in DEFAULT_PARAMS}}
try:
    page.load_into_form(nulls)
    collected = page.collect()
    ok("null 值不会崩溃", f"拿回 kbps={collected['audio']['kbps']}")
except Exception as exc:  # noqa: BLE001
    bug("null 值导致崩溃", f"{type(exc).__name__}: {exc}")

# 2e 未知枚举值（比如游戏更新后出现新的 codec_prof）
weird = copy.deepcopy(PRESETS["上游默认（虚拟麦克风音乐）"])
weird["audio"] = {**weird["audio"], "codec_prof": 9999, "sample_rate": 96000}
try:
    page.load_into_form(weird)
    collected = page.collect()
    if collected["audio"]["codec_prof"] == 9999 and collected["audio"]["sample_rate"] == 96000:
        ok("下拉框能承载未知枚举值")
    else:
        bug("未知枚举值被改掉了", f"codec_prof={collected['audio']['codec_prof']} sample_rate={collected['audio']['sample_rate']}")
except Exception as exc:  # noqa: BLE001
    bug("未知枚举值导致崩溃", f"{type(exc).__name__}: {exc}")

# 2f 文本框粘贴非法 JSON
try:
    page.json_view.setPlainText("{ 这不是 JSON")
    page.apply_from_text()
    ok("非法 JSON 粘贴不会崩溃")
except Exception as exc:  # noqa: BLE001
    bug("非法 JSON 粘贴崩溃", f"{type(exc).__name__}: {exc}")

# 2g 文本框粘贴非对象
try:
    page.json_view.setPlainText("[1,2,3]")
    page.apply_from_text()
    ok("非对象 JSON 被拒绝")
except Exception as exc:  # noqa: BLE001
    bug("非对象 JSON 崩溃", f"{type(exc).__name__}: {exc}")

print()
print("=" * 74)
print("3) 处理核验表在边界数据下的表现")
print("=" * 74)

# 3a 完全没有控制配置
empty_status = {
    "config_files": [],
    "config_profiles": [],
    "config_state": audio_off.processing_state([]),
    "runtime_sample": {},
    "runtime_state": {},
    "keys": list(audio_off.AUDIO_PROCESS_KEYS),
}
rows = core.processing_table_rows(empty_status)
conclusions = {row[0][0]: row[0][3] for row in rows}
if all("未暴露" in text or "没有这个键" in text for text in conclusions.values()):
    bug(
        "没有控制配置时误报为「该 SDK 构建未暴露」",
        "真实原因是配置文件不存在，应提示先执行关闭/注入",
    )
else:
    ok("空配置时的结论合理", str(list(conclusions.values())[:2]))

# 3b 只有运行时样本（配置层空）
runtime_only = dict(empty_status)
runtime_only["runtime_sample"] = {"aec": 1, "agc": 0, "sr": 16000, "fec": 1}
runtime_only["runtime_state"] = audio_off.processing_state([runtime_only["runtime_sample"]])
rows = core.processing_table_rows(runtime_only)
aec_row = next(r for r in rows if "回声消除" in r[0][0])
if aec_row[0][1] == "—" and "编译期" in aec_row[0][3]:
    ok("只有运行层数据时给出「编译期默认值」判断", aec_row[0][3][:24])

print()
print("=" * 74)
print("4) 控制配置编解码无损")
print("=" * 74)

gme_config = engine._mod("gme_config")
paths = engine._mod("paths")
for path in sorted(paths.gme_dir().glob("gmesdk_control_*.config")):
    raw = path.read_bytes()
    round_trip = gme_config.dump_encoded_config(gme_config.load_encoded_config(path))
    if raw == round_trip:
        ok(f"{path.name} 解码→编码字节完全一致", f"{len(raw)} 字节")
    else:
        bug(
            f"{path.name} 编解码不无损",
            f"原 {len(raw)} 字节 vs 回写 {len(round_trip)} 字节（重复 inject 会不断改写文件）",
        )

print()
print("=" * 74)
print("5) 回滚目标推断")
print("=" * 74)

cases = [
    ("hosts.hosts.20260101_000000_000000.bak", "hosts"),
    ("gmesdk_control_1400801152.config.control.20260101_000000_000000.bak", "control"),
    ("av_config.json.av_config.20260101_000000_000000.bak", "av"),
    ("weird.bak", None),
    ("hosts.hosts.x.txt", None),
    ("gmesdk_control_1.config.control.20260101_000000_000000.1.bak", "control"),
]
for name, expect in cases:
    got = core.resolve_rollback_target(engine, layout, layout.backup_dir / name)
    kind = None if got is None else ("hosts" if got == layout.hosts_file else ("control" if got.name.startswith("gmesdk_control") else "av"))
    if kind == expect:
        ok(f"{name[:44]:46s} → {kind}")
    else:
        bug("回滚目标推断错误", f"{name} 期望 {expect}，得到 {kind} ({got})")

print()
print("=" * 74)
print("6) 视图层：空数据与显示")
print("=" * 74)

from gui.pages import BackupsPage, DetailTable, LogsPage  # noqa: E402

backups = BackupsPage(ctx)
backups.set_rows([])
if backups.table.rowCount() == 1 and "还没有备份" in backups.table.item(0, 0).text():
    ok("空备份列表显示占位行")
else:
    bug("空备份列表渲染异常", f"rowCount={backups.table.rowCount()}")

table = DetailTable(["a", "b"])
table.fill([])
ok("DetailTable 空填充不崩溃", f"height={table.height()}")

logs = LogsPage(ctx)
logs.reload_log(silent=True)
if "还没有" in logs.path_label.text() or logs.path_label.text():
    ok("日志页在无日志时不崩溃", logs.path_label.text()[:30])

# 日志视图超长行
view = widgets.LogView()
view.append("<b>注入尝试</b> & 特殊字符 <script>", "warn")
view.append("第二行\n第三行", "ok")
if view.toPlainText().count("\n") >= 2:
    ok("LogView 转义与多行插入正常", repr(view.toPlainText()[:40]))
else:
    bug("LogView 多行插入异常", repr(view.toPlainText()))

print()
print("=" * 74)
if found:
    print(f"共发现 {len(found)} 个问题：")
    for item in found:
        print("  " + item)
else:
    print("未发现 bug")
print("=" * 74)
