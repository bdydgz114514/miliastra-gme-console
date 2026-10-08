r"""持久性体检：确认「改完是否一劳永逸」。

检查四件事：
1. 控制配置是否仍是只读、处理是否仍全关（游戏是否会把它改回去）
2. hosts 屏蔽段是否生效（域名是否真的解析不出去）
3. 最新日志里 GME 还有没有成功拉到远程配置
4. 最近一次语音参数是否已切到目标方案

    python gui\persistence_check.py
"""

from __future__ import annotations

import re
import socket
import sys
from datetime import datetime
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

from gui import audio_off  # noqa: E402
from gui.core import GmeEngine, discover_layout  # noqa: E402

engine = GmeEngine(discover_layout())
paths = engine._mod("paths")
gme_config = engine._mod("gme_config")

print("=" * 74)
print("1) 控制配置文件")
print("=" * 74)
found_any = False
for path in sorted(paths.gme_dir().glob("gmesdk_control_*.config")):
    found_any = True
    stat = path.stat()
    config = gme_config.load_encoded_config(path)
    data = config.get("data", {})
    profiles = gme_config.summarize_config(config)
    state = audio_off.processing_state(profiles)
    on = audio_off.enabled_keys(state)
    print(f"  文件      : {path.name}")
    print(f"  大小/时间 : {stat.st_size} B / {datetime.fromtimestamp(stat.st_mtime)}")
    print(f"  只读      : {not bool(stat.st_mode & 0o200)}")
    print(f"  sequence  : {data.get('sequence')}  (被顶到上限就不会再接受云端更小的版本)")
    print(f"  remote_ip : {config.get('remote_ip')!r}   retcode={config.get('retcode')!r}")
    print(f"  处理开关  : {'全部关闭 OK' if not on else '仍开着 -> ' + '、'.join(on)}")
if not found_any:
    print(f"  没有找到控制配置文件（目录：{paths.gme_dir()}）")
    print("  -> 说明还没执行过「关闭全部音频处理」或 inject")

print()
print("=" * 74)
print("2) hosts 屏蔽是否真的生效")
print("=" * 74)
hosts = engine.hosts_block()
print(f"  hosts 文件: {hosts['path']}")
print(f"  屏蔽段存在: {hosts['installed']}")
for domain in hosts["blocked_hosts"]:
    try:
        addresses = socket.gethostbyname_ex(domain)[2]
    except OSError:
        # 解析失败 = 请求根本出不去 = 屏蔽成功（hosts 生效时的正常表现）
        addresses = []
    if not addresses:
        verdict = "解析失败，请求出不去 -> 已屏蔽 OK"
    elif all(addr.startswith(("0.0.0.0", "127.", "::")) for addr in addresses):
        verdict = "被解析到黑洞地址 -> 已屏蔽 OK"
    else:
        verdict = "仍能解析到真实 IP -> 屏蔽未生效"
    print(f"  {domain:26s} -> {addresses or '无结果'}  {verdict}")

print()
print("=" * 74)
print("3) 最新日志里 GME 还能不能拿到远程配置")
print("=" * 74)
log = engine.latest_log_path()
if log is None:
    print("  没有 GMESDK 日志")
else:
    pattern = re.compile(
        r"AVControlConfig (?P<event>json string|invalid json string|error|http response ok)"
    )
    hits: list[tuple[str, str]] = []
    with log.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = pattern.search(line)
            if match:
                hits.append((line[:12].strip(), match.group("event")))
    print(f"  日志文件: {log.name}（最后写入 {datetime.fromtimestamp(log.stat().st_mtime)}）")
    print(f"  AVControlConfig 事件共 {len(hits)} 条，最后 8 条：")
    for stamp, event in hits[-8:]:
        if event == "error":
            flag = " <- 拉取失败 = hosts 屏蔽生效 OK"
        elif event in {"json string", "http response ok"}:
            flag = " <- 远程配置下发成功（屏蔽可能没生效）"
        else:
            flag = ""
        print(f"    {stamp}  {event}{flag}")

print()
print("=" * 74)
print("4) 最近一次语音参数（确认游戏已切到新方案）")
print("=" * 74)
# status.runtime_log_status 依赖 TARGET_AUDIO 已填充，必须先加载参数
engine._mod("audio_params").load_audio_params()
runtime = engine._mod("status").runtime_log_status()
sample = runtime.get("target_sample") or {}
if sample:
    print(f"  记录时间: {runtime.get('target_sample_time')}")
    print(f"  配置时间: {runtime.get('latest_config_time')}")
    print(
        f"  AEC={sample.get('aec')} AGC={sample.get('agc')} ANS={sample.get('ans')} "
        f"AINS={sample.get('ains')} VAD={sample.get('vad')} FEC={sample.get('fec')}"
    )
    print(
        f"  采样率={sample.get('sr')} 声道={sample.get('ch')} 码率={sample.get('br')} "
        f"缓冲={sample.get('jitter_init')}/{sample.get('jitter_min')}-{sample.get('jitter_max')}"
    )
    print(f"  判定: {runtime.get('runtime_status')}  (effective={engine.full_status()['effective']})")
else:
    print("  日志里还没有语音参数记录")

print()
print("=" * 74)
print("5) 备份与落点")
print("=" * 74)
rows = engine.list_backups()
for row in rows:
    print(f"  {row['mtime']}  {row['kind']:<16} {row['name']}")
if not rows:
    print("  backups/ 为空（还没执行过任何写入操作）")
for target in paths.local_av_config_targets():
    mark = "已写入 OK" if target.exists() else "不存在"
    print(f"  av_config: {target}  -> {mark}")
