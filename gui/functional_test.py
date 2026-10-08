r"""功能自测：验证参数保存、回滚路径推断、备份列表解析等写入路径（不触碰真实 GME 配置）。

    python gui\functional_test.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import sys

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

from gui.core import GmeEngine, discover_layout  # noqa: E402
from gui import core  # noqa: E402

layout = discover_layout()
engine = GmeEngine(layout)
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


# ---- 1. 参数文件往返 ---- #
original = layout.audio_params.read_bytes()
try:
    payload = engine.load_params_raw()
    check("读取 audio_params.json", isinstance(payload, dict) and "audio" in payload)

    engine.validate_params(payload)
    check("校验上游默认参数", True)

    mutated = json.loads(json.dumps(payload))
    mutated["audio"]["jitter_init"] = 777
    engine.save_params_raw(mutated)
    reloaded = engine.load_params_raw()
    check("保存后回读 jitter_init", reloaded["audio"]["jitter_init"] == 777, str(reloaded["audio"]["jitter_init"]))

    bad = json.loads(json.dumps(payload))
    bad["audio"]["bitrate"] = 1000
    try:
        engine.validate_params(bad)
    except Exception as exc:  # noqa: BLE001
        check("bitrate < kbps*1000 被拒绝", "bitrate" in str(exc), str(exc))
    else:
        check("bitrate < kbps*1000 被拒绝", False, "没有报错")

    bad2 = json.loads(json.dumps(payload))
    del bad2["audio"]["aec"]
    try:
        engine.validate_params(bad2)
    except Exception as exc:  # noqa: BLE001
        check("缺字段被拒绝", "aec" in str(exc), str(exc))
    else:
        check("缺字段被拒绝", False, "没有报错")
finally:
    layout.audio_params.write_bytes(original)
    check("恢复 audio_params.json 原始内容", layout.audio_params.read_bytes() == original)

# ---- 2. 回滚路径推断 ---- #
from gui.core import resolve_rollback_target  # noqa: E402

fake_hosts = layout.backup_dir / "hosts.hosts.20260101_000000_000000.bak"
fake_control = layout.backup_dir / "gmesdk_control_1400801152.config.control.20260101_000000_000000.bak"
fake_av = layout.backup_dir / "av_config.json.av_config.20260101_000000_000000.bak"

check("hosts 备份 → hosts 路径", resolve_rollback_target(engine, layout, fake_hosts) == layout.hosts_file)
control_target = resolve_rollback_target(engine, layout, fake_control)
check(
    "控制配置备份 → GME 目录同名文件",
    control_target is not None and control_target.name == "gmesdk_control_1400801152.config",
    str(control_target),
)
av_target = resolve_rollback_target(engine, layout, fake_av)
check(
    "av_config 备份 → 本地 av_config.json",
    av_target is not None and av_target.name == "av_config.json",
    str(av_target),
)
check("无法识别的备份返回 None", resolve_rollback_target(engine, layout, layout.backup_dir / "weird.bak") is None)
check("非 .bak 文件返回 None", resolve_rollback_target(engine, layout, layout.backup_dir / "hosts.hosts.x.txt") is None)

# ---- 3. 备份列表解析（用临时文件，不动真实 backups/）---- #
backup_dir = layout.backup_dir
backup_dir.mkdir(parents=True, exist_ok=True)
before = {p.name for p in backup_dir.glob("*.bak")}
stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
sample = backup_dir / f"hosts.hosts.{stamp}.bak"
sample.write_text("# sample\n", encoding="utf-8")
try:
    rows = engine.list_backups()
    found = [row for row in rows if row["name"] == sample.name]
    check("备份列表包含新文件", bool(found), f"{len(rows)} 行")
    check("备份类型识别为 hosts", bool(found) and found[0]["kind"] == "hosts")
finally:
    sample.unlink(missing_ok=True)
after = {p.name for p in backup_dir.glob("*.bak")}
check("清理临时备份", before == after)

# ---- 4. 只读视图 ---- #
controls = engine.decoded_control_configs()
check("控制配置解码", len(controls) >= 1 and bool(controls[0]["profiles"]), f"{len(controls)} 个文件")
hosts_info = engine.hosts_block()
check("hosts 状态可读", "installed" in hosts_info, f"installed={hosts_info['installed']}")
status = engine.full_status()
check(
    "full_status 关键字段齐全",
    all(key in status for key in ("effective", "runtime", "hosts", "configs", "diagnosis")),
    f"effective={status['effective']}",
)
log_path, lines = engine.tail_log(20, "AudParam")
if log_path is None:
    # 全新机器上还没有 GMESDK 日志（没装游戏、或还没进过语音场景），
    # 这时不能判定失败——跳过后面的断言，保证自检在任何环境都能跑通。
    print("[skip] 本机还没有 GMESDK 日志 —— 跳过「日志尾部 + 过滤」断言")
else:
    check(
        "日志尾部 + 过滤",
        len(lines) <= 20,
        f"{log_path.name}, {len(lines)} 行",
    )
    # 过滤应当真的起作用：用一句几乎不可能出现的关键字，结果必须是 0 行
    _, none_lines = engine.tail_log(20, "zzz-this-keyword-cannot-exist-zzz")
    check("关键字过滤生效（无匹配时返回空）", none_lines == [], f"{len(none_lines)} 行")

# ---- 5. 「关闭全部音频处理」逻辑 ---- #
from gui import audio_off  # noqa: E402

# 用审计出来的真实结构造一份配置（含 upstream 不会碰的 silence_detect）
sample_config = {
    "data": {
        "conf": {
            "index000": {
                "type": 1,
                "role": "esports",
                "audio": {
                    "aec": 1, "agc": 1, "ans": 1, "anti_dropout": 1, "au_scheme": 8,
                    "channel": 1, "codec_prof": 4129, "frame": 40, "kbps": 18,
                    "max_antishake_max": 1000, "max_antishake_min": 400, "min_antishake": 200,
                    "sample_rate": 16000, "silence_detect": 1,
                },
            },
            "index001": {
                "type": 5,
                "role": "host",
                "audio": {
                    "aec": 1, "agc": 0, "ans": 0, "anti_dropout": 0, "au_scheme": 5,
                    "channel": 2, "codec_prof": 4106, "frame": 40, "kbps": 64,
                    "sample_rate": 48000, "silence_detect": 1,
                    "vad": 1, "dtx": 1,  # 某些 SDK 构建才有的键
                },
            },
        }
    }
}

changes = audio_off.force_off_config(sample_config)
changed_keys = sorted({item["key"] for item in changes})
check(
    "force_off 关掉全部处理键（含 silence_detect / vad / dtx）",
    changed_keys == ["aec", "agc", "ans", "dtx", "silence_detect", "vad"],
    str(changed_keys),
)
check("force_off 不动 FEC", sample_config["data"]["conf"]["index000"]["audio"]["anti_dropout"] == 1)
check("force_off 不动编解码/码率", sample_config["data"]["conf"]["index001"]["audio"]["kbps"] == 64)

state = audio_off.processing_state([item["audio"] for item in audio_off.iter_profiles(sample_config)])
processing_only = {key: info for key, info in state.items() if key in audio_off.AUDIO_PROCESS_KEYS}
check(
    "处理后所有处理项 any_on=False",
    all(not info["any_on"] for info in processing_only.values()),
    str({key: info["values"] for key, info in processing_only.items()}),
)
check("FEC 仍在（保留项）", state["anti_dropout"]["any_on"] is True)
check("aec 在 profile 里被置 0", sample_config["data"]["conf"]["index000"]["audio"]["aec"] == 0)

check("重复执行无改动（幂等）", audio_off.force_off_config(sample_config) == [])

# 缺键时不应该凭空造键
sparse = {"data": {"conf": {"1": {"audio": {"aec": 1}}}}}
audio_off.force_off_config(sparse)
check("缺键不凭空创建", set(sparse["data"]["conf"]["1"]["audio"]) == {"aec"})

# ---- 6. 本机控制配置与运行日志的只读核验 ----
# 注意：这一节依赖「本机已经装过游戏并跑过语音」。
# 全新克隆的机器上两个来源都可能为空，所以用「有则验、无则跳过」的方式，
# 保证本测试在任何环境下都能通过。
real = engine.audio_processing_status()
if real["config_profiles"]:
    check("能读到控制配置 profile", True, f"{len(real['config_profiles'])} 个 profile")
    rows = core.processing_table_rows(real)
    labels = [row[0][0] for row in rows]
    check(
        "核验表覆盖 AEC/AGC/ANS/静音检测 + FEC 行",
        any("回声消除" in name for name in labels)
        and any("自动增益" in name for name in labels)
        and any("普通降噪" in name for name in labels)
        and any("silence_detect" in name for name in labels)
        and any("FEC" in name for name in labels),
        " / ".join(labels),
    )
    real_aec = real["config_state"].get("aec") or {}
    check(
        "能读出配置层 AEC 的状态（值取决于本机是否已关闭）",
        bool(real_aec.get("present")),
        f"values={real_aec.get('values')} all_off={real_aec.get('all_off')}",
    )
    # 结论文案必须与状态自洽：开着就不能说已关闭，关着就不能说还需要执行
    aec_row = next(row for row in rows if "回声消除" in row[0][0])
    if real_aec.get("any_on"):
        check("AEC 开着时结论提示去关闭", "关闭全部音频处理" in aec_row[0][3] or "重进" in aec_row[0][3], aec_row[0][3])
    else:
        check("AEC 已关时结论不会误报", "仍开着" not in aec_row[0][3], aec_row[0][3])
else:
    print("[skip] 本机没有控制配置文件 —— 跳过「核验表内容」相关断言")
    # 空数据也要能渲染出合理结论，不能谎称「SDK 未暴露」
    rows = core.processing_table_rows(real)
    check(
        "无控制配置时结论不谎称「SDK 未暴露」",
        all("未暴露" not in row[0][3] for row in rows),
        rows[0][0][3] if rows else "(无行)",
    )

if real["runtime_sample"]:
    check("能读到运行层样本", True, str(real["runtime_sample"].get("raw", ""))[:60])
else:
    print("[skip] 本机没有 GMESDK 语音参数记录（游戏还没进过语音场景）—— 跳过运行层断言")

if not real["config_profiles"] and not real["runtime_sample"]:
    print()
    print("提示：本节所有断言都在空数据下跳过。要跑完整核验，请先安装游戏并进一次语音场景。")

# ---- 7. 「关闭全部音频处理」真写盘测试（在临时目录里，不碰生产 GME 目录） ---- #
gme_config = engine._mod("gme_config")
original_settings = engine.layout.settings.read_text(encoding="utf-8")
backups_before = {item.name for item in engine.layout.backup_dir.glob("*.bak")}
tmp_root = Path(tempfile.mkdtemp(prefix="miliastra-test-"))
fake_gme = tmp_root / "GME" / "YuanShen.exe"
fake_game = tmp_root / "Genshin Impact Game"
fake_gme.mkdir(parents=True)
fake_game.mkdir(parents=True)

config_path = fake_gme / "gmesdk_control_1400801152.config"
seed = {
    "data": {
        "scheme": 3,
        "sequence": 0,
        "conf": {
            "index000": {
                "type": 1,
                "role": "esports",
                "is_default": 1,
                "audio": {
                    "aec": 1, "agc": 1, "ans": 1, "anti_dropout": 1, "au_scheme": 8,
                    "channel": 1, "codec_prof": 4129, "frame": 40, "kbps": 18,
                    "max_antishake_max": 1000, "max_antishake_min": 400, "min_antishake": 200,
                    "sample_rate": 16000, "silence_detect": 1,
                },
            },
            "index004": {
                "type": 5,
                "role": "host",
                "is_default": 0,
                "audio": {
                    "aec": 1, "agc": 0, "ans": 0, "anti_dropout": 0, "au_scheme": 5,
                    "channel": 2, "codec_prof": 4106, "frame": 40, "kbps": 64,
                    "sample_rate": 48000, "silence_detect": 1,
                },
            },
        },
    }
}
config_path.write_bytes(gme_config.dump_encoded_config(seed))
encoded_before = config_path.read_bytes()

try:
    engine.save_settings(
        {
            "process_name": "YuanShen.exe",
            "module_name": "gmesdk.dll",
            "gme_dir": str(fake_gme),
            "game_dir": str(fake_game),
        }
    )

    manifest = engine.apply_audio_off()
    decoded = gme_config.load_encoded_config(config_path)
    audio_a = decoded["data"]["conf"]["index000"]["audio"]
    audio_b = decoded["data"]["conf"]["index004"]["audio"]

    check("控制配置确实被改写", config_path.read_bytes() != encoded_before)
    check(
        "两个 profile 的处理开关全部归零",
        audio_a["aec"] == 0 and audio_a["agc"] == 0 and audio_a["ans"] == 0
        and audio_a["silence_detect"] == 0 and audio_b["aec"] == 0 and audio_b["silence_detect"] == 0,
        json.dumps({"index000": audio_a, "index004": audio_b}, ensure_ascii=False),
    )
    check("FEC 被保留", audio_a["anti_dropout"] == 1)
    check("码率/采样率未被改动", audio_a["kbps"] == 18 and audio_a["sample_rate"] == 16000)
    check(
        "改写前有备份",
        bool(manifest["configs"][0]["backup"]) and Path(manifest["configs"][0]["backup"]).exists(),
        str(manifest["configs"][0]["backup"]),
    )
    check("控制配置被设为只读", not (config_path.stat().st_mode & 0o200))

    av_targets = [Path(item["path"]) for item in manifest["av_configs"]]
    check("写入了 GME 目录下的 av_config.json", (fake_gme / "av_config.json").exists())
    check("写入了游戏目录下的 av_config.json", (fake_game / "av_config.json").exists())
    check(
        "av_config.json 里的处理开关也是关的",
        audio_off.force_off_config(json.loads((fake_gme / "av_config.json").read_text(encoding="utf-8"))) == [],
    )
    check("manifest 记录了改动位置数", len(manifest["changes"]) >= 6, f"{len(manifest['changes'])} 处")

    # 再跑一次应当是幂等的
    manifest2 = engine.apply_audio_off()
    check("重复执行幂等（无新增改动）", manifest2["changes"] == [], f"{len(manifest2['changes'])} 处")
finally:
    engine.layout.settings.write_text(original_settings, encoding="utf-8")

    def _force_writable(func, path, _exc):  # noqa: ANN001
        try:
            Path(path).chmod(0o666)
            func(path)
        except OSError:
            pass

    shutil.rmtree(tmp_root, onexc=_force_writable)
    check("临时目录已清理", not tmp_root.exists())

    # 清掉本次测试写到真实 backups/ 的备份文件，避免干扰用户
    leftovers = sorted(
        str(item)
        for item in engine.layout.backup_dir.glob("*.bak")
        if item.name not in backups_before
    )
    for name in leftovers:
        try:
            Path(name).chmod(0o666)
            Path(name).unlink()
        except OSError:
            pass
    remaining = [
        str(item)
        for item in engine.layout.backup_dir.glob("*.bak")
        if item.name not in backups_before
    ]
    check("测试产生的备份已清理", not remaining, f"清理前 {len(leftovers)} 个；残留 {remaining}")

check("settings.json 已还原", engine.layout.settings.read_text(encoding="utf-8") == original_settings)
engine._mod("audio_params").load_audio_params()  # 还原 TARGET_AUDIO

# ---- 8. 参数预设校验 ---- #
from gui.pages import PRESETS  # noqa: E402

for name, preset in PRESETS.items():
    try:
        engine.validate_params(preset)
    except Exception as exc:  # noqa: BLE001
        check(f"预设「{name}」合法", False, str(exc))
    else:
        check(f"预设「{name}」合法", True)

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    raise SystemExit(1)
print("全部功能自测通过。")
