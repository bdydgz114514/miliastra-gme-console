r"""音频卡顿排查：带宽占用、GME 抖动/丢包、运行时缓冲、OBS 环路与滤镜链。

只读，不修改任何东西。

    python gui\stutter_diagnose.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

from gui.core import GmeEngine, discover_layout  # noqa: E402

engine = GmeEngine(discover_layout())
paths = engine._mod("paths")
obs = Path.home() / "AppData" / "Roaming" / "obs-studio"
MONITORING = {0: "关闭", 1: "仅监听", 2: "监听并输出"}
problems: list[str] = []


def section(title: str) -> None:
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def flag(text: str) -> None:
    problems.append(text)
    print(f"  [问题] {text}")


section("0) 上行带宽占用（回答「是不是带宽不够」）")
try:
    engine._mod("audio_params").load_audio_params()
    profile = engine.audio_profile()
    target = profile["target"]
    kbps = target.get("kbps") or 0
    runtime = engine._mod("status").runtime_log_status()
    sample = runtime.get("target_sample") or {}
    actual = (sample.get("br") or 0) / 1000
    print(f"  目标方案: {profile['name']}")
    print(f"  采样率/声道/帧长: {target.get('sample_rate')} Hz / {target.get('channel')} ch / {target.get('frame')} ms")
    print(f"  目标码率: {kbps} kbps = {kbps / 8:.1f} KB/s")
    if actual:
        print(f"  实际运行: {actual:.0f} kbps = {actual / 8:.1f} KB/s")
    print(f"  占 20 Mbps 上行: {kbps / 20000 * 100:.3f}%")
    print(f"  占 4 Mbps 上行 : {kbps / 4000 * 100:.2f}%")
    print("  结论: 码率在十几 KB/s 量级，任何能上网的线路都不缺这点上行。")
except Exception as exc:  # noqa: BLE001
    print(f"  读取参数失败：{exc}")

section("1) OBS 音频路由：采集源 × 监听设备（找环路）")
basic = next((obs / "basic" / "profiles").glob("*/basic.ini"), None)
monitor_device = ""
if basic:
    text = basic.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"MonitoringDeviceName=(.+)", text)
    monitor_device = m.group(1).strip() if m else ""
    print(f"  OBS 监听设备 = {monitor_device or '（未设置）'}")
    if "CABLE Input" in monitor_device:
        flag(
            "OBS 的「监听设备」就是 CABLE Input：监听混音会被重新写回同一条虚拟线，"
            "和节目混音叠加 → 对面听到重复/断续的音频"
        )

scene_files = sorted((obs / "basic" / "scenes").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
if scene_files:
    data = json.loads(scene_files[0].read_text(encoding="utf-8", errors="replace"))
    print(f"  场景集合: {scene_files[0].name}")
    print()

    global_devices = [
        ("桌面音频", data.get("DesktopAudioDevice1")),
        ("麦克风/辅助音频", data.get("AuxAudioDevice1")),
    ]
    print("  --- 全局音频设备 ---")
    for label, device in global_devices:
        if not device:
            continue
        print(
            f"  [{label}] 设备={device.get('settings', {}).get('device_id', '?')[:46]} "
            f"音量={device.get('volume')} 监听={MONITORING.get(device.get('monitoring_type'), '?')}"
        )
        if device.get("monitoring_type") == 2 and "CABLE Input" in monitor_device:
            flag(f"「{label}」是「监听并输出」，且监听回 CABLE Input → 自我叠加")
        if device.get("volume") == 0.0:
            print("      （音量为 0，实际不出声）")

    print()
    print("  --- 场景内的源 ---")
    for source in data.get("sources", []):
        sid = source.get("id", "")
        if sid == "scene":
            continue
        settings = source.get("settings") or {}
        mon = MONITORING.get(source.get("monitoring_type"), "?")
        print(f"  [{sid}] {source.get('name')}  监听={mon} 音量={source.get('volume')}")
        if sid == "window_capture":
            window = settings.get("window", "")
            print(f"      窗口: {window[:90]}")
            print(f"      采集音频: {settings.get('capture_audio')}")
            if settings.get("capture_audio") and source.get("monitoring_type") == 2 and "CABLE Input" in monitor_device:
                flag(
                    "「窗口采集」开了音频采集且是「监听并输出」，监听又回 CABLE Input → "
                    "被采集的窗口音频（含游戏/浏览器）会被再灌回虚拟线，游戏收到重复副本"
                )
        if sid == "wasapi_process_output_capture":
            print(f"      目标进程: {settings.get('window')}")

section("2) 麦克风滤镜链（算法本身可能造成断续）")
if scene_files:
    aux = data.get("AuxAudioDevice1") or {}
    filters = aux.get("filters") or []
    if not filters:
        print("  麦克风上没有滤镜")
    for index, item in enumerate(filters, 1):
        name = item.get("name")
        enabled = item.get("enabled")
        settings = item.get("settings") or {}
        print(f"  {index}. {name}  [{item.get('id')}] 启用={enabled}")
        print(f"     {json.dumps(settings, ensure_ascii=False)}")
        if not enabled:
            continue
        if item.get("id") == "expander_filter":
            flag("「扩展效果」默认参数会把语音电平往下压，是断续/发闷的经典来源")
        if item.get("id") == "noise_suppress_filter" and str(settings.get("method")) == "rnnoise":
            print("      （RNNoise 对音乐/伴奏不友好，会误判为人声以外的内容并抑制）")
        if item.get("id") == "compressor_filter":
            release = settings.get("release_time")
            if isinstance(release, (int, float)) and release >= 100:
                flag(f"压缩器 release_time={release} ms 偏长，语音会出现抽吸感（gain pumping）")

section("3) GME 网络层：socket 溢出与会话重建")
log = engine.latest_log_path()
if log is None:
    print("  没有 GMESDK 日志")
else:
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"  日志: {log.name}  {len(lines)} 行  最后写入 {datetime.fromtimestamp(log.stat().st_mtime):%Y-%m-%d %H:%M}")
    overflow = [line for line in lines if "overFlow" in line]
    starts = [line for line in lines if "Network Thread Start" in line]
    resets = [line for line in lines if "BufferAdjust Reset" in line]
    print(f"  xpsocket 池溢出 : {len(overflow)} 次")
    print(f"  网络线程重建    : {len(starts)} 次")
    print(f"  抖动缓冲重置    : {len(resets)} 次")
    if overflow:
        flag(f"SDK 报 {len(overflow)} 次 socket 池溢出，重传/心跳会失败，直接表现为上行断续")
    if len(starts) > 10:
        flag(f"网络线程重建 {len(starts)} 次，会话频繁重连本身就是卡顿来源")

    # 下行丢包补偿计数
    conceal = []
    for line in lines:
        m = re.search(r"BufferStatistic:.*\[(\d+)\|(\d+)\|(\d+)\|(\d+)\]", line)
        if m and any(int(x) > 0 for x in m.groups()):
            conceal.append(tuple(int(x) for x in m.groups()))
    print(f"  下行丢包补偿计数为非零的采样点: {len(conceal)} 个")
    if conceal:
        worst = max(conceal, key=lambda t: max(t))
        print(f"    最大一次: {worst}  → 链路上确实有丢包被 FEC/隐藏补掉（这一项是下行）")

section("4) 采样率一致性")
for ini in (obs / "basic" / "profiles").glob("*/basic.ini"):
    text = ini.read_text(encoding="utf-8", errors="replace")
    sr = re.search(r"SampleRate=(\d+)", text)
    cs = re.search(r"ChannelSetup=(\w+)", text)
    print(f"  OBS: {sr.group(1) if sr else '?'} Hz / {cs.group(1) if cs else '?'}")
try:
    target = engine.audio_profile()["target"]
    print(f"  GME: {target.get('sample_rate')} Hz / {target.get('channel')} ch")
except Exception:  # noqa: BLE001
    pass

section("结论")
if problems:
    print(f"  发现 {len(problems)} 个可疑问题（按影响排序）：")
    for index, item in enumerate(problems, 1):
        print(f"  {index}. {item}")
    print()
    print("  注意：这些问题都在「采集/路由」侧，跟上行带宽无关。")
else:
    print("  没有发现明显的采集/路由问题。")
