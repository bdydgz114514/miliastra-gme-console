# MiliastraGME 控制台

给 [clearyss/MiliastraGME](https://github.com/clearyss/MiliastraGME) 做的**图形界面 + 部署工具 + 中文教程**。

上游是一个命令行小工具：把自定义音频参数写进腾讯 GME（游戏多媒体引擎）的本地配置，并在 hosts 里屏蔽云端配置下发，让游戏语音按你的参数运行。本项目在**完全不修改上游代码**的前提下，用 PySide6 给它加了一层桌面界面，并补齐了上游没做的几件事。

> 📖 **完整使用教程见 [TUTORIAL.md](TUTORIAL.md)** —— 面向没接触过命令行的用户，从装 Python 到验证生效，约 15 分钟。

---

## 这个界面解决了什么

上游 CLI 能用，但有三个实际痛点：

| 痛点 | 本项目怎么解决 |
| --- | --- |
| 控制配置是**位移异或编码**的，看不到实际值 | **解码成表格**，直接看到 6 个 profile 的真实参数 |
| 判定是否生效要肉眼比对两段文本 | **逐项对比表**，差异标黄；另有「配置层 / 运行层 / 结论」三列核验表 |
| `restore` **不会**回滚被改写的控制配置，容易回不去 | 新增**「备份与回滚」页**，按文件名自动推断原路径，一键还原 |

另外补了两个上游的漏洞：

- **上游只写 `aec / agc / ans / ains / vad`，漏了 `dtx` 和 `silence_detect`** —— 而 `silence_detect` 恰恰是某些 SDK 构建里唯一生效的静音检测键名
- **游戏目录探测**只查 `Win32_Process.ExecutablePath`，对启动器拉起的进程常常取不到；本项目做了三级回退（`Win32_Process` → `Get-Process/MainModule` → 启动器目录 + 注册表）

## 功能

**六个页面**

| 页面 | 内容 |
| --- | --- |
| **总览** | 生效状态胶囊、**游戏自带音频处理逐项核验表**、目标 vs 实际 14 项对比、诊断建议、关键路径 |
| **参数方案** | 表单化编辑 `audio_params.json`、5 套预设、JSON 实时预览、保存前校验 |
| **高级配置** | `settings.json` 编辑、控制配置解码表、`av_config.json` 落点、hosts 屏蔽段原文 |
| **备份与回滚** | 列出 `backups/`，一键回滚被改写的配置 |
| **日志与输出** | GME 运行日志（行数/关键字过滤/自动刷新）+ 工具操作输出 |
| **帮助与说明** | 原理、命令对照、判定逻辑、风险提示 |

**「关闭全部音频处理」**（总览页 / 参数方案页）

把每个 profile 的 `aec / agc / ans / ains / vad / dtx / silence_detect` 全部写 0，并同步写入 3 处 `av_config.json`；**保留 `anti_dropout`（FEC 丢包保护）**，它不是音频处理。

与上游 `inject` 的区别：**不碰 hosts**。想只关处理、不想对抗远程配置时用这个。

**配套脚本**

| 脚本 | 用途 |
| --- | --- |
| `gui/persistence_check.py` | 只读体检：配置层/运行层是否全关、hosts 是否真挡住、日志事件时间线、备份列表 |
| `gui/status_report.py` | 只读巡检：进度总览、备份、路径 |
| `gui/stutter_diagnose.py` | 语音卡顿排查：上行带宽占用、**OBS 音频环路检测**、麦克风滤镜链可疑参数、GME 网络层异常 |
| `gui/bug_hunt.py` | 边界/并发自测（任务队列状态机、畸形输入、空数据渲染） |
| `gui/functional_test.py` | 写入路径自测（在临时 GME 目录里做，不动生产配置） |
| `gui/smoke_test.py` | 无头烟雾测试 + 六页截图 |

## 快速开始

需要 **Windows + Python 3.10+**。

```cmd
git clone https://github.com/<你的用户名>/miliastra-gme-console.git
cd miliastra-gme-console
install.cmd
```

或者手动：

```cmd
python -m pip install PySide6
python gui\app.py --check
python gui\app.py
```

界面里点 **「探测游戏目录」**，再点 **「关闭全部音频处理」**，然后**进一次游戏语音场景**让引擎重读配置，最后点「刷新状态」确认。

详细步骤（含每一步的预期结果和排错）见 **[TUTORIAL.md](TUTORIAL.md)**。

## 界面预览

> 截图待补充。运行 `python gui\smoke_test.py` 会在 `screenshots/` 生成六个页面的截图。

## 工作原理

```
audio_params.json ──┐
                    ├─→ 解码控制配置 → 改写 audio 段 → 设为只读
settings.json ──────┤                    ↓
                    │            sequence = 2147483647（云端无法覆盖）
                    ├─→ 写入 av_config.json × 3 处（本地覆盖配置）
                    └─→ hosts 屏蔽 gmeconf/gmeosconf.qcloud.com

GMESDK_*.log ──→ 解析 PrepareEncParam/SetAudParam ──→ 与目标参数逐项比对 ──→ 生效判定
```

关键点：**改动全部落在磁盘文件上**，不是靠后台进程盯着。所以配置一次之后，重启电脑、重启游戏都不需要重新运行本工具。只有游戏大版本更新后建议复查一次。

## 与上游的关系

| | |
| --- | --- |
| 上游项目 | [clearyss/MiliastraGME](https://github.com/clearyss/MiliastraGME) |
| 上游许可证 | GPL-3.0 |
| 本项目对上游代码的修改 | **无**。通过 `importlib` 以合法包名加载上游模块（目录名带连字符无法直接 import），只读取与调用 |
| 本项目许可证 | GPL-3.0（因包含上游代码，沿用同一许可证） |
| 归属声明 | 见 [NOTICE](NOTICE) |

上游目录结构在本仓库中保持原样，因此本仓库同时是一个**可直接使用的完整部署**（上游 + 界面）。

## 安全说明

- 本仓库**不含任何凭据**。`.gitignore` 已排除 `data/`、`backups/`、`screenshots/`（这些目录可能含本机路径与 GME 日志片段）
- 首次运行前请检查 `settings.json`，它记录的是**你自己的**游戏路径
- 上游 `README.md` 保留在仓库中，其中的交流 QQ 群等信息属于上游作者

## 风险提示

本项目会修改系统 `hosts`、GME 配置目录和游戏安装目录文件，其中「屏蔽远程配置域名」属于**对抗云端下发的行为**。

- 可能导致语音功能异常、配置无法更新、安全软件拦截、账号风险提示或限制
- 可能违反游戏用户协议，**是否使用请自行判断**
- 上游作者与本项目作者均不对使用后果负责
- 不再使用时请执行 `restore` **并手动回滚控制配置**（`restore` 不会自动做这件事，界面里提供了回滚功能）
- 本项目与米哈游、腾讯均无关联

## 致谢

- [clearyss/MiliastraGME](https://github.com/clearyss/MiliastraGME) —— 核心逻辑与配置格式的全部逆向工作
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) —— 虚拟音频线（音频路由场景）
