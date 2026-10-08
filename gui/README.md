# MiliastraGME 控制台（gui/）

给上游 [MiliastraGME](https://github.com/clearyss/MiliastraGME) 加的一层桌面界面。
**不改上游任何一行代码**：界面通过 `importlib` 加载仓库根目录的上游模块，
直接调用它的 `audio_params` / `gme_config` / `hosts` / `status` 能力，写入的数据格式与上游 CLI 完全一致。

```
miliastra-gme-console/
├─ audio_params.py  gme_config.py  hosts.py  status.py  …   ← 上游原样，未修改
├─ install.cmd              ← 一键安装（检查 Python、装 PySide6、自检、可选建快捷方式）
├─ run-gui.cmd              ← 普通权限启动界面
├─ run-gui-admin.cmd        ← 以管理员身份启动界面（桌面「控制台」快捷方式指向它）
├─ 体检.ps1                  ← 只读体检包装（桌面「体检」快捷方式指向它，需 UTF-8 BOM）
├─ make_shortcuts.ps1       ← 重建桌面快捷方式（可重复执行，自动定位仓库根目录）
├─ TUTORIAL.md              ← 面向新手的完整中文教程
├─ NOTICE                   ← 上游归属与 GPL-3.0 声明
├─ docs/UPSTREAM-README.md  ← 上游 README 原样保留
└─ gui/                     ← 本界面
   ├─ app.py                 入口
   ├─ core.py                引擎层（加载上游包 / 后台任务队列 / 提权 / 备份回滚 / 关闭全部处理）
   ├─ audio_off.py           「关闭全部音频处理」的判定与修补（纯数据变换，可单测）
   ├─ widgets.py             配色、样式表、卡片、胶囊、日志视图等通用组件
   ├─ pages.py               六个页面
   ├─ shell.py               主窗口：侧边导航 + 顶部动作栏 + 状态栏
   ├─ health_check.ps1       体检的纯 ASCII 主体（被 体检.ps1 调用，标题由外层传入）
   ├─ persistence_check.py   只读巡检：配置层/运行层状态、hosts 屏蔽、日志事件、备份列表
   ├─ status_report.py       只读巡检：进度总览 + 备份 + 路径
   ├─ make_icon.py           零依赖生成 icon.ico（手写 PNG/ICO 编码，不用 Qt）
   ├─ functional_test.py     写入路径自测（不动生产 GME 配置）
   ├─ bug_hunt.py            边界/并发自测（状态机、畸形输入、空数据）
   └─ smoke_test.py          无头烟雾测试 + 六页截图
```

## 桌面快捷方式

`make_shortcuts.ps1` 会在桌面创建两个快捷方式（可重复执行，覆盖旧的）：

| 快捷方式 | 行为 | 何时用 |
| --- | --- | --- |
| **MiliastraGME 控制台** | 调 `run-gui-admin.cmd`，弹一次 UAC 后以管理员开界面 | 调参 / 关闭音频处理 / inject / restore |
| **MiliastraGME 体检** | `powershell -File 体检.ps1`，只读打印当前状态，结束前暂停 | 游戏更新后、或怀疑失效时复查 |

重建方式：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File make_shortcuts.ps1
```

> 踩过的坑：Windows PowerShell 5.1 会把**无 BOM 的 UTF-8** 当 ANSI 读，脚本里的中文
> `Write-Host` 会直接把字符串引号吃掉、整个文件语法错误。所以含中文的 `.ps1` 必须存成
> **UTF-8 with BOM**（`体检.ps1` 就是），其余脚本一律写成纯 ASCII（`health_check.ps1`、
> `run-gui-admin.cmd` 都是）。

## 启动

```powershell
# 方式一：普通权限（推荐先这样用）
双击 run-gui.cmd
python gui\app.py

# 方式二：管理员权限（inject / restore / 回滚 不再弹 UAC）
双击 run-gui-admin.cmd
```

其它用法：

```powershell
python gui\app.py --check        # 只做自检：路径、方案、生效状态、权限、控制配置数量
python gui\app.py --run status   # 直接跑一次上游子命令并把输出打到控制台
```

## 页面

| 页面 | 干什么 | 需要管理员 |
| --- | --- | :-: |
| **总览** | 生效状态胶囊、**游戏自带音频处理逐项核验表**、14 项「目标 vs 游戏实际」对比表、诊断与建议、关键路径 | 否 |
| **参数方案** | 表单化编辑 `audio_params.json`：音质参数、6 个处理开关、jitter 缓冲、5 套预设、JSON 预览与校验，以及「关闭全部游戏内音频处理」入口 | 否（保存即写文件） |
| **高级配置** | `settings.json` 编辑、`gmesdk_control_*.config` **解码后**的六个 profile 表、`av_config.json` 落点、hosts 屏蔽段 | 保存 settings 否 |
| **备份与回滚** | 列出 `backups/` 里的原始文件，按文件名推断原路径并一键回滚 | 回滚是 |
| **日志与输出** | GMESDK 运行日志（行数 / 关键字过滤 / 自动刷新）+ 本工具的操作输出 | 否 |
| **帮助与说明** | 原理、命令对照、生效判定含义、风险提示 | 否 |

## 关闭全部游戏内音频处理

界面上有两条路径，按你的需要选：

**A. 只关处理（推荐，不动 hosts）** —— 总览页「关闭全部音频处理」按钮

会逐个 profile 把 `gmesdk_control_*.config` 里的处理开关写 0，并同步写 `av_config.json`：

| 键 | 含义 | 处理 |
| --- | --- | :-: |
| `aec` | 回声消除 | → 0 |
| `agc` | 自动增益 | → 0 |
| `ans` | 普通降噪 | → 0 |
| `ains` | AI 降噪（部分 SDK 构建才有） | → 0 |
| `vad` | 静音检测（部分 SDK 构建才有） | → 0 |
| `dtx` | 不连续发送（部分 SDK 构建才有） | → 0 |
| `silence_detect` | 静音检测（本机 SDK 用的就是这个键名） | → 0 |
| `anti_dropout` | 丢包保护 FEC | **保留**（不是音频处理，关掉会断音） |

比上游 `inject` 多做的三件事：

1. **补上 `dtx`** —— 上游只写 aec/agc/ans/ains/vad。
2. **补上 `silence_detect`** —— 上游把它硬编码成 0，但没有覆盖到所有 profile 的所有分支。
3. **不动 hosts** —— 想只关处理、不想对抗远程配置时用这条。

**B. 关处理 + 锁定远程配置** —— 顶栏「注入参数（inject）」

在 A 的基础上再往 `hosts` 写 GME 屏蔽段，防止云端策略把你的本地设置覆盖回去。代价是这属于对抗远程配置下发的行为。

### 怎么确认真的关掉了

总览页的「游戏自带音频处理」表分三层看：

- **配置层** —— 解码后的 `gmesdk_control_*.config` 实际值
- **游戏运行时** —— `GMESDK_*.log` 里 `PrepareEncParam` 的最新记录
- **结论** —— 逐项给出「已关闭」/「配置里仍开着」/「运行时仍是旧值，重进一次语音场景」等判断

几个容易踩的坑，表里会直接标出来：

- 某个键在配置里**根本不存**在（本机 `ains` / `vad` / `dtx` 就是），写了也不生效，属引擎编译期默认值。
- 配置已经关了、但运行时日志还是旧值 —— 必须**重进一次游戏语音场景**，引擎才会重新 `SetAudParam`。
- 日志时间早于配置修改时间时，判定是 `stale_*`，不代表失败。

## 权限模型

- 界面顶部会显示当前是否为管理员。
- `inject` / `restore` / 备份回滚在**非管理员**下会走 `ShellExecuteW(runas)`：
  弹一次 UAC → 开一个独立 PowerShell 窗口执行 → 窗口保留输出。
  **提权进程的输出无法回传到本进程**，所以执行完请回到界面点「刷新状态」。
- 也可以点侧边栏的「以管理员身份重启界面」，之后所有操作都在界面内直接执行。
- 只读操作（看状态、看日志、看配置、改参数）都不需要管理员。

## 界面相对 CLI 多做的事

- 把 `gmesdk_control_*.config`（位移异或编码）**解码**成表格，直接看到六个 profile 的实际参数。
- 把「目标参数 vs 游戏实际参数」逐项对比并标色，不用再肉眼比对两段文本。
- **「游戏自带音频处理」逐项核验表**：配置层 / 运行层 / 结论三列，一眼看出哪个开关没关干净、
  是配置没写进去还是日志没刷新。
- **一键关闭全部音频处理**：补齐上游漏掉的 `dtx` / `silence_detect`，且不碰 hosts。
- 参数表单带校验（缺字段、`bitrate < kbps*1000` 等会当场报错），保存前可先校验。
- 备份回滚：上游 `restore` 不会回滚 `gmesdk_control_*.config`，这里可以从 `backups/` 一键还原
  （回滚前会先把当前文件另存一份 `.before_rollback.<时间戳>.bak`）。
- 游戏目录探测：上游只查 `Win32_Process.ExecutablePath`（启动器拉起的进程常常取不到），
  这里按 `Win32_Process → Get-Process/MainModule → 启动器目录 + 注册表` 三级回退，
  探到后自动写进 `settings.json`，这样配置才能覆盖到游戏安装目录下的 `av_config.json`。

## 自测

```powershell
python gui\functional_test.py    # 参数往返、校验规则、回滚路径推断、备份解析、
                                 # 「关闭全部处理」真写盘（在临时 GME 目录里做，不动生产配置）
python gui\bug_hunt.py           # 边界与并发：任务队列状态机、畸形输入、空数据渲染、编解码无损
python gui\smoke_test.py         # 无头构建整个界面、跑完异步任务、六个页面各存一张截图
python gui\status_report.py      # 只读巡检：配置层/运行层是否全关、备份列表、av_config 落点
python gui\stutter_diagnose.py   # 语音卡顿排查：上行带宽占用、GME 抖动/丢包记录、
                                 # 运行时缓冲参数、OBS 音频告警
```

`functional_test.py` 会把 `settings.json` 指向临时目录、跑完还原，并清掉测试期间产生的备份，
不会污染你的真实 GME 配置。

静态检查（环境里已装 flake8 / pyflakes）：

```powershell
python -m pyflakes gui          # 期望无输出
python -m flake8 --select=E9,F --max-line-length=200 gui
```

`smoke_test.py` 用 `QT_QPA_PLATFORM=offscreen` 跑，不需要显示器；截图默认写到 `screenshots/`。
若截图里中文显示成方块，是 offscreen 平台没加载到中文字体，可临时指定：

```powershell
$env:QT_QPA_FONTDIR='C:\Windows\Fonts'; python gui\smoke_test.py
```

## 风险提示（与上游一致）

- `inject` 会改系统 `hosts`、`%APPDATA%\GME\...` 下的控制配置和 `av_config.json`，并把这些文件设为只读。
- 屏蔽 GME 远程配置域名属于对抗云端下发的行为，是否违反游戏用户协议请自行判断。
- `restore` **不会**回滚被改写的 `gmesdk_control_*.config`，必须用「备份与回滚」页手动还原。
- 效果取决于游戏版本、GME SDK 版本、输入设备、虚拟声卡与系统音频设置，不保证一定生效。
- 上游为 GPL-3.0；本界面同样按 GPL-3.0 使用。
