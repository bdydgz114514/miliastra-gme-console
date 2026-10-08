"""「关闭全部游戏内音频处理」的判定与修补逻辑。

背景（基于本机 GME 控制配置解码 + GMESDK 日志实测）：

GME 的音频处理开关分两个地方下发：

* ``conf.<profile>.audio`` —— 采集端 DSP
    - ``aec``            回声消除
    - ``agc``            自动增益
    - ``ans``            普通降噪
    - ``ains``           AI 降噪（部分 SDK 构建有）
    - ``vad``            静音检测（部分 SDK 构建有）
    - ``dtx``            不连续发送（部分 SDK 构建有）
    - ``anti_dropout``   丢包保护（FEC，**不属于处理，建议保留**）
    - ``silence_detect`` 静音检测（本机 SDK 用的是这个键名）
* ``conf.<profile>.net`` —— 服务端下行侧的抖动/丢包策略
    - ``rc_anti_dropout`` 下行丢包保护
    - ``rc_init_delay`` / ``rc_max_delay`` 下行缓冲

上游 ``gme_config.patch_profile`` 只处理 aec/agc/ans 和写死的 ains/vad，
既不写 dtx，也不动 net，所以「把处理关干净」这件事需要额外补一层。

本模块只做数据变换，不做 IO，方便单测。
"""

from __future__ import annotations

from typing import Any, Iterable

# 采集端「音频处理」开关：这些都是「关闭全部处理」要归零的
AUDIO_PROCESS_KEYS: tuple[str, ...] = ("aec", "agc", "ans", "ains", "vad", "dtx", "silence_detect")

# 状态核验时要一起看的键（含保留项 FEC）
STATUS_KEYS: tuple[str, ...] = (*AUDIO_PROCESS_KEYS, "anti_dropout")

# 传给人看的名字
KEY_LABELS: dict[str, str] = {
    "aec": "回声消除 AEC",
    "agc": "自动增益 AGC",
    "ans": "普通降噪 ANS",
    "ains": "AI 降噪 AINS",
    "vad": "静音检测 VAD",
    "dtx": "不连续发送 DTX",
    "silence_detect": "静音检测 silence_detect",
    "anti_dropout": "丢包保护 FEC（保留）",
}

# 这些键写 0 表示「关闭处理」
FORCE_OFF_KEYS: tuple[str, ...] = AUDIO_PROCESS_KEYS


# 这些键在 config 原文 / 上游 summarize_config 摘要 / 运行日志样本里的名字各不相同
KEY_SOURCES: dict[str, tuple[str, ...]] = {
    "aec": ("aec",),
    "agc": ("agc",),
    "ans": ("ans",),
    "ains": ("ains",),
    "vad": ("vad",),
    "dtx": ("dtx",),
    "silence_detect": ("silence_detect", "silence"),
    "anti_dropout": ("anti_dropout", "fec"),
}


def pick(row: dict, key: str) -> Any:
    """从一行摘要/样本里按键取值（兼容 config / 摘要 / 日志三种命名）。"""

    for name in KEY_SOURCES.get(key, (key,)):
        if name in row:
            return row[name]
    return None


def iter_profiles(config: dict) -> list[dict]:
    """遍历一份控制配置里的所有 profile（上游 conf 可能是 dict 或 list）。"""

    conf = (config.get("data") or {}).get("conf") or {}
    if isinstance(conf, dict):
        return [item for item in conf.values() if isinstance(item, dict)]
    if isinstance(conf, list):
        return [item for item in conf if isinstance(item, dict)]
    return []


def force_off_config(config: dict) -> list[dict]:
    """把所有 profile 的音频处理开关全部写 0，返回每个 profile 的改动明细。"""

    changes: list[dict] = []
    for index, item in enumerate(iter_profiles(config)):
        audio = item.setdefault("audio", {})
        detail: list[dict] = []
        for key in FORCE_OFF_KEYS:
            before = audio.get(key)
            if before is None:
                continue  # 这个 SDK 构建里没有该键，不强行造出来
            if before != 0:
                audio[key] = 0
                detail.append({"profile": index, "scope": "audio", "key": key, "before": before, "after": 0})
        changes.extend(detail)
    return changes


def processing_state(profiles: Iterable[dict]) -> dict[str, dict[str, Any]]:
    """汇总一组 profile 里每个处理开关的状态。

    返回值形如 ``{"aec": {"present": True, "values": [0, 0], "all_off": True}}``。
    """

    result: dict[str, dict[str, Any]] = {}
    rows = list(profiles)
    for key in STATUS_KEYS:
        values: list[Any] = []
        for row in rows:
            value = pick(row, key)
            if value is not None:
                values.append(value)
        result[key] = {
            "present": bool(values),
            "values": values,
            "all_off": bool(values) and all(value == 0 for value in values),
            "any_on": any(value not in (0, None) for value in values),
        }
    return result


def label(key: str) -> str:
    return KEY_LABELS.get(key, key)


def enabled_keys(state: dict[str, dict[str, Any]], only_processing: bool = True) -> list[str]:
    """从 processing_state() 结果里挑出仍然开着的键（默认排除 FEC 这类保留项）。"""

    keys = AUDIO_PROCESS_KEYS if only_processing else STATUS_KEYS
    return [key for key in keys if (state.get(key) or {}).get("any_on")]


def missing_keys(state: dict[str, dict[str, Any]]) -> list[str]:
    """本机 SDK 构建里不存在的处理键。"""

    return [key for key in AUDIO_PROCESS_KEYS if not (state.get(key) or {}).get("present")]


def summarize(changes: list[dict]) -> str:
    if not changes:
        return "已经是全部关闭状态，无需修改。"
    return f"共关闭 {len(changes)} 处处理开关。"
