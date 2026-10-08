r"""无头烟雾测试：构建主窗口、跑一轮异步任务、遍历所有页面并截图。

    python gui\smoke_test.py [截图输出目录]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui import core, widgets  # noqa: E402
from gui.shell import MainWindow  # noqa: E402


def pump(app: QApplication, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else GUI_DIR.parent / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    layout = core.discover_layout()
    print(f"[smoke] repo = {layout.root}")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(widgets.STYLESHEET)

    window = MainWindow(layout)
    window.resize(1400, 950)
    window.show()

    # 等异步任务（params / status）跑完，否则页面还是空壳
    deadline = time.time() + 25
    while (window.tasks.busy or window.tasks.pending) and time.time() < deadline:
        pump(app, 0.2)
    pump(app, 1.0)

    dashboard = window.pages["dashboard"]
    print(f"[smoke] 仪表盘状态胶囊 = {dashboard.hero_chip.text()!r}")
    print(f"[smoke] 仪表盘说明     = {dashboard.hero_message.text()!r}")
    print(f"[smoke] 对比表行数     = {dashboard.compare_table.rowCount()}")
    print(f"[smoke] 诊断条目数     = {dashboard.diag_body.count()}")
    print(f"[smoke] 状态栏         = {window.profile_label.text()!r}")

    # 音频处理核验（只读）
    window.refresh_audio_off()
    deadline = time.time() + 15
    while (window.tasks.busy or window.tasks.pending) and time.time() < deadline:
        pump(app, 0.2)
    pump(app, 0.6)
    print(f"[smoke] 音频处理胶囊   = {dashboard.proc_chip.text()!r}")
    print(f"[smoke] 音频处理表行数 = {dashboard.proc_table.rowCount()}")
    for row in range(dashboard.proc_table.rowCount()):
        cells = [dashboard.proc_table.item(row, col).text() for col in range(4)]
        print("        " + " | ".join(cells))
    hint = dashboard.proc_hint.text().splitlines()
    for line in hint:
        print("    hint:", line)

    for key in ("dashboard", "params", "advanced", "backups", "logs", "help"):
        window.go_to(key)
        pump(app, 1.5)
        target = out_dir / f"gui-{key}.png"
        window.grab().save(str(target))
        print(f"[smoke] {key:10s} -> {target.name}")

    print("[smoke] 操作日志尾部：")
    text = window.action_log.toPlainText().strip().splitlines()
    for line in text[-14:]:
        print("   ", line)
    print(f"[smoke] 日志共 {len(text)} 行")

    window.tasks.shutdown()
    window.close()
    pump(app, 0.3)
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
