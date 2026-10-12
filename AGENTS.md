# MCHOSE 电量托盘

Windows 系统托盘小工具：实时显示 MCHOSE 鼠标（K7 V2 Ultra+）与键盘（K99 V3）的电量，无需官方驱动。自行逆向了 2.4G 接收器的私有 HID 协议，支持 2.4G 与蓝牙两种连接方式。

## 运行方式

- Windows 专用（Win32 HID / tkinter / winreg / uxtheme），Python 3.12。
- 依赖：`pip install -r requirements.txt`（hidapi / pystray / Pillow，pyinstaller 可选）。
- 双击 `start.bat` 后台无窗口启动（自动定位 pythonw.exe）；托盘右键菜单"退出"结束进程。
- 或直接运行打包产物 `dist\MCHOSEBattery.exe`。

## 常用命令

| 用途 | 命令 | 出处 |
|---|---|---|
| 启动（无控制台） | `pythonw tray_app.py` 或双击 `start.bat` | tray_app.py 模块注释 / start.bat |
| 只读一次电量并退出 | `python tray_app.py --selftest` | tray_app.py `main()` |
| 冒烟测试（托盘 5 秒自动退出） | `python tray_app.py --smoke` | tray_app.py `main()` |
| 查看版本 | `python tray_app.py --version` | tray_app.py `main()` |
| 单元测试 | `python -m unittest discover tests`（31 个纯函数用例） | tests/test_frames.py / tests/test_behavior.py |
| 打包独立 exe | `pyinstaller --onefile --noconsole --name MCHOSEBattery tray_app.py` | README.md"打包为独立 exe" |

## 目录结构

- `battery.py` — 读取层：鼠标 2.4G 私有协议实时查询、键盘推送常驻监听线程、蓝牙 GATT 属性兜底；协议解析抽为模块顶部纯函数（可单测）。
- `tray_app.py` — 托盘 UI 与主入口（pystray + Pillow 自绘图标）：轮询、低电量通知、开机自启（HKCU Run）、单实例互斥量、深色菜单。
- `float_window.py` — 桌面电量浮窗（tkinter 无边框置顶、按 DPI 缩放、拖动与大小记忆，配置在 `%LOCALAPPDATA%\MCHOSEBattery\widget.json`）。
- `tray_icon.py` — ctypes Shell_NotifyIcon 自绘托盘的备选实现，当前未被任何模块 import（tray_app 实际用 pystray）。
- `log.py` — 共用滚动日志（`%LOCALAPPDATA%\MCHOSEBattery\logs\app.log`，1MB×2）。
- `widget_diag.py` — 浮窗 12 秒真机诊断脚本，核对四档实际尺寸，结果写入应用日志。
- `tests/test_frames.py` — 协议解析单元测试（纯函数，不碰真机 HID）。
- `tests/test_behavior.py` — 读取优先级、缓存有效性、低电量状态转换与缩放纯函数回归测试。
- `tools/` — 逆向过程的探测/抓包/分析脚本与完整报文记录 kb_capture.log，协议结论可复核。
- `edgeposter/`、`dist/`、`__pycache__/`、`build*/` — 非源码（Edge CDP 抓包浏览器配置目录 / 构建产物），git 已忽略，勿提交。

## 工程约定

- 协议解析写成 battery.py 顶部无副作用的纯函数；单测覆盖解析与策略纯函数，不 mock 真机。
- 日志统一 `log.get_logger(name)`，不用 print；设 `MCHOSE_DEBUG=1` 额外输出 DEBUG 到 stderr。
- GUI 调控制台子进程必须带 `CREATE_NO_WINDOW`（0x08000000）；PowerShell 输出按 mbcs 解码（UTF-8 解码线程遇非 ASCII 字节会崩，v3.0 的教训）。
- `.gitignore` 是白名单模式（默认全忽略、逐个 `!` 放行）：新增源文件/测试/工具脚本必须手动加白名单，否则不会被 git 跟踪。
- 提交信息大致遵循 conventional commits（feat / fix / tune / style / perf / release）。
- 运行时数据只存 `%LOCALAPPDATA%\MCHOSEBattery\`（keyboard.json 推送缓存 / widget.json 浮窗配置 / logs/）。
- 代码注释与文档用简体中文，命令、路径、技术标识保持英文。

## 项目特定注意事项

- 键盘 K99 V3 的 2.4G 模式固件**没有电量查询命令**，只能被动收推送（放电过程静默，插拔充电线必推送）。改键盘读取逻辑前先读 README"协议备忘"与 `battery.read_keyboard()` 的 docstring。
- 读取优先级是刻意设计：蓝牙硬在线（实时）> 各自 2.4G 通道 > 蓝牙闲置缓存（24h 内）。`FA FB 06` 链路广播会立即作废 BLE 扫描缓存；动这套顺序前先理解 v2.1.1 / v3.0 的修复历史，历史上三次回归都出在这里。
- 单实例靠命名互斥量 `MCHOSEBattery_SingleInstance`；`--selftest` 故意绕过守卫，改 `main()` 时别破坏这一点。
- 深色托盘菜单走 uxtheme 未公开接口 135/136（SetPreferredAppMode / FlushMenuThemes），必须在主线程调用。
- 真机行为（HID 协议、蓝牙缓存、固件推送）单测覆盖不了，改动读取层后至少跑一次 `--selftest` 并真机观察。
- 浮窗尺寸按"逻辑像素 × 实际 DPI 缩放系数 × 用户档位"处理，系数保留小数（见 float_window.py 设计令牌）；本次真机诊断测得 175%，200% 也已做渲染验证。

## 当前维护说明

- 当前版本 `3.2`；低电量 ≤15% 连续三次提醒，恢复至 >20% 重新布防，未知读数打断连续计数。
- 蓝牙正常缓存 120 秒、失败重试 15 秒；历史间歇性超时需要结合新的详细日志持续观察。
- 键盘推送缓存最长采用 24 小时，接收器缺失或已知断链时不采用；尚无本次推送则标为“2.4G 缓存”。
- `--selftest` 不创建监听线程；正常退出等待 HID 读取/监听线程结束，禁止在 DLL 卸载后继续访问句柄。
- `tray_icon.py` 保留作备选，当前未接入；`widget_diag.py` 与纯函数回归测试已纳入 Git 白名单。
