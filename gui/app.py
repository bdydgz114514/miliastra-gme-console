"""MiliastraGME 控制台入口。

用法：
    python -m gui            # 启动图形界面
    python gui/app.py        # 同上
    python gui/app.py --check   # 只做自检并退出（不开窗口）
    python gui/app.py --run status   # 直接跑一次上游子命令并打印输出
"""

from __future__ import annotations

import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
if str(GUI_DIR.parent) not in sys.path:
    sys.path.insert(0, str(GUI_DIR.parent))
if __package__ in (None, ""):
    sys.path.insert(0, str(GUI_DIR))
    __package__ = "gui"

from gui import core, widgets  # noqa: E402


def self_check() -> int:
    layout = core.discover_layout()
    engine = core.GmeEngine(layout)
    profile = engine.audio_profile()
    status = engine.full_status()
    print(f"仓库目录     : {layout.root}")
    print(f"参数文件     : {layout.audio_params}")
    print(f"GME 数据目录 : {engine._mod('paths').gme_dir()}")
    print(f"当前方案     : {profile['name']} / {profile['target_text']}")
    print(f"生效状态     : {'已生效' if status['effective'] else '待确认'}（{status['runtime']['runtime_status']}）")
    print(f"管理员权限   : {'是' if core.is_admin() else '否'}")
    print(f"控制配置     : {len(engine.decoded_control_configs())} 个")
    print(f"备份文件     : {len(engine.list_backups())} 个")
    print("自检通过：GUI 依赖的上游能力都能调用。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if "--check" in args:
        return self_check()

    if "--run" in args:
        index = args.index("--run")
        command = args[index + 1] if index + 1 < len(args) else "status"
        layout = core.discover_layout()
        result = core.run_cli(layout, command)
        print(result.text, flush=True)
        return result.returncode

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from gui.shell import MainWindow

    layout = core.discover_layout()
    app = QApplication(sys.argv)
    app.setApplicationName("MiliastraGME 控制台")
    app.setApplicationDisplayName("MiliastraGME 控制台")
    app.setStyle("Fusion")
    app.setStyleSheet(widgets.STYLESHEET)

    icon_path = GUI_DIR / "assets" / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(layout)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
