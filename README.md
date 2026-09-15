# MCHOSE 电量托盘

在 Windows 系统托盘实时显示 MCHOSE 鼠标和键盘电量的小工具。无需安装 MCHOSE 官方驱动。

## 当前状态

| 设备 | 连接方式 | 电量读取 |
|---|---|---|
| 鼠标 K7 V2 Ultra+ | 2.4G 接收器 (PID 0x1014) | ✅ 实时查询（私有协议已破解，与官方 M HUB 显示一致） |
| 鼠标 K7 V2 Ultra+ | 蓝牙 | ✅ 读 Windows 蓝牙电量属性 |
| 键盘 K99 V3 | 2.4G 接收器 (PID 0x3033) | ✅ 被动监听电量推送（见下） |
| 键盘 K99 V3 | 蓝牙 | ✅ 读 Windows 蓝牙电量属性（**可实时查询**，对电量敏感时推荐切蓝牙） |

## 更新记录

### v2.1
- **新增蓝牙连接模式支持**：鼠标/键盘切蓝牙后自动改读 Windows 蓝牙标准电量属性（GATT Battery Service）。
  判在线以 HID-over-GATT 集合存在为准——BTHLE 节点断开后仍显示"在线"且电量是陈旧缓存，不可作为判据。
  蓝牙查询带 60 秒缓存；PowerShell 子进程已加 CREATE_NO_WINDOW（不弹黑窗）。
- 键盘切蓝牙后即可实时读电量，绕开 2.4G 推送式延迟；蓝牙模式暂无充电标志。

### v2.0
- 修复 MANUAL_REPORT 推送帧解析（帧头字段校验错误导致周期推送被全部丢弃）
- 键盘监听器每 10 分钟重发握手，尝试刺激固件上报
- 悬停标注推送时间（分钟/小时），数据新旧一目了然
- 修正文档：明确放电过程无推送的固件行为（附官方会话抓包证据）
- 修复鼠标查询等待循环的忙等待（无响应时 CPU 占用从 ~2% 降至 ~0.01%）

### v1.0
- 首个版本：鼠标实时查询 + 键盘推送监听 + 托盘 UI / 低电量通知 / 开机自启

## 使用

- 双击 `start.bat` 启动（无窗口后台运行），或直接运行 `dist\MCHOSEBattery.exe`。
- 托盘图标上的数字即鼠标电量百分比（>50 绿 / 20-50 橙 / ≤20 红，充电时显示闪电）。
- 鼠标悬停图标可看完整信息（设备电量、连接方式、推送时间）；左键点击立即刷新。
- 右键菜单：立即刷新 / 低电量提醒开关 / 开机自启 / 退出。
- 电量 ≤20% 时弹一次 Windows 通知，回到 25% 以上重新布防。
- 鼠标深度休眠/关机导致查询失败时图标变 "--"，动一下鼠标即恢复。
- 键盘首次收到推送前显示 "--"，插拔一次键盘充电线即可触发；或切蓝牙模式获得实时读数。

依赖（源码运行）：Python 3.12 + `pip install hidapi pystray Pillow`。

## 打包为独立 exe

```bat
pip install pyinstaller
pyinstaller --onefile --noconsole --name MCHOSEBattery tray_app.py
```

生成 `dist\MCHOSEBattery.exe`；"开机自启"菜单项在 exe 模式下同样有效。

## 文件说明

- `battery.py` — 读取层。鼠标：2.4G 私有 HID 协议实时查询；键盘：常驻线程监听电量推送并落盘缓存；蓝牙：Windows 电量属性兜底（两台设备均支持）。
- `tray_app.py` — 托盘 UI（pystray + Pillow 自绘图标）。
- `tools/` — 逆向过程中的探测/抓包/分析脚本与完整报文记录（kb_capture.log），可复核协议结论。

## 协议备忘（鼠标，已验证）

接收器 `VID_3837&PID_1014` 的 interface 2 / usagePage 0xFF01 / usage 0x0001 集合：

- 查询：output report `0x4D`，载荷 `[01 01 00 00 09 00 00 cs]` + 零填充至 64 字节，
  `cs` = 除版本字节外全部异或（空载荷时 cs=0x08）。
- 回复：input report `0x4D`，`raw[4:6]==00 09` 匹配；`raw[8]==0xFF` 表示忙需重发；
  连接状态 `raw[18]`（2=2.4G）、充电 `raw[19]`、**电量 `raw[20]`**。
- 命令 0x0900 即官方 M HUB 的"鼠标信息"查询；同族命令 0x0001/0x0002/0x0003/0x0009
  可读配置/灵敏度等（未使用）。

### 键盘 K99 V3（已逆向，2.4G 推送式）

接收器 `PID_3033` 的命令通道为 usagePage 1/usage 0 集合（report 无编号，0x00 前缀）：
- Z 帧查询：`[55 cmd 00 cs size offLo offHi 00 ...]`，cs = size^offLo^offHi^00，
  应答 `[AA cmd 00 len size offLo offHi 00 data...]`；
  cmd 3=getInfo（含"2.4G Dongle"字串）、4=getBase（板载 profile）、5=配置、8=键矩阵、A0=灯光。
- 电量**无查询命令**（官方 JS 的 getBattery(0x0904) M 帧属于其他型号的 Qhw 通道，
  键盘集合的描述符为无编号报告，M 帧不可用），只有两类异步推送：
  - `FA FB 07 <电量%> <充电标志>`（充电事件广播；`FA FB 06` 为连接状态广播）；
  - MANUAL_REPORT（命令 0x0700）：`[AA 07 00 len size offLo offHi 00 data[0..22]]`，
    data[2]=充电(0未充/1充电/2满) data[3]=电量% data[4]=连接(1有线/2无线)。
- tools/ 下有完整抓包（kb_capture.log）与复刻脚本可复核。

### 蓝牙模式（两台设备通用）

- 在线判据：`HID\{00001812*}_DEV_VID&..XXXX_PID&XXXX_REV&XXXX_<MAC>\` 集合 PresentOnly 存在。
- 电量：同 MAC 的 `BTHLE\DEV_<MAC>\*` 设备的 `DEVPKEY_Device_BatteryLevel`（GATT Battery Service，
  Windows 缓存值，设备在线时由系统经 GATT 更新）。
- 归属：按 FriendlyName 匹配（K7 → 鼠标，K99 → 键盘）。

## 已知限制

- 键盘 2.4G 模式电量为推送式：数值变化滞后到下次推送（实测放电过程静默，
  插拔充电线必推送）；需要实时数值请将键盘切到蓝牙模式。
- 蓝牙模式读不到充电标志（Windows 属性只有百分比）。
- 电量数值由设备固件估算（电压查表），通常较长时间才变化 1%，属正常现象。
- 鼠标 2.4G 读取周期 5 秒，蓝牙查询 60 秒缓存；接收器拔插后自动恢复。
