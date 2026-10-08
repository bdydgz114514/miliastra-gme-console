r"""用户巡检：打印当前界面需要知道的一切（只读，不改任何东西）。"""

from __future__ import annotations

import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

from gui import audio_off, core  # noqa: E402
from gui.core import GmeEngine, discover_layout  # noqa: E402

engine = GmeEngine(discover_layout())
layout = engine.layout

print("=" * 74)
print("当前进度")
print("=" * 74)
status = engine.audio_processing_status()
config_on = audio_off.enabled_keys(status["config_state"])
runtime_on = audio_off.enabled_keys(status["runtime_state"])
print(f"控制配置层：{'全部关闭 ✅' if not config_on else '仍开着 → ' + '、'.join(config_on)}")
print(f"游戏运行时：{'全部关闭 ✅' if not runtime_on else '仍开着 → ' + '、'.join(runtime_on)}")
print(f"扫描到的配置文件：{status['config_files']}")

sample = status["runtime_sample"]
if sample:
    print(f"\n日志里最新一次音频参数（{sample.get('raw', '')[:40]}…）：")
    print(f"  AEC={sample.get('aec')} AGC={sample.get('agc')} ANS={sample.get('ans')} "
          f"AINS={sample.get('ains')} VAD={sample.get('vad')} FEC={sample.get('fec')}")
    print(f"  采样率={sample.get('sr')} 声道={sample.get('ch')} 码率={sample.get('br')}")

runtime = engine._mod("status").runtime_log_status()
print(f"\n记录时间：{runtime.get('target_sample_time')}")
print(f"配置修改时间：{runtime.get('latest_config_time')}")
print(f"判定：{runtime.get('runtime_status')}  （日志是否晚于配置：{runtime.get('verification_valid')}）")

print()
print("=" * 74)
print("备份文件（出问题时的后悔药）")
print("=" * 74)
for row in engine.list_backups():
    print(f"  {row['mtime']}  {row['kind']:<16} {core.human_size(row['size']):>8}  {row['name']}")

print()
print("=" * 74)
print("当前生效方案（audio_params.json）")
print("=" * 74)
profile = engine.audio_profile()
print(f"  名称：{profile['name']}")
print(f"  说明：{profile['description']}")
print(f"  参数：{profile['target_text']}")

print()
print("=" * 74)
print("界面所需的路径")
print("=" * 74)
paths = engine._mod("paths")
print(f"  GME 数据目录：{paths.gme_dir()}")
print(f"  游戏目录    ：{paths.game_dir()}")
for target in paths.local_av_config_targets():
    mark = "已写入 ✅" if target.exists() else "不存在"
    print(f"  av_config   ：{target}  → {mark}")
hosts = engine.hosts_block()
print(f"  hosts 屏蔽段：{'已安装' if hosts['installed'] else '未安装（当前方案不碰 hosts）'}")
