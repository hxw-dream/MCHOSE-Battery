"""MCHOSE 电量读取层（鼠标 2.4G 接收器专用，不含蓝牙支持）。

鼠标 K7 V2 Ultra+（2.4G 接收器 VID 0x3837 / PID 0x1014）——已真机验证:
  HID 集合: interface 2, usagePage 0xFF01, usage 0x0001
  查询: output report 0x4D, 载荷 [01 01 00 00 09 00 00 cs] + 零填充至 64 字节
        cs = 除去版本字节(首字节 0x01)后所有字节的异或
  回复: input report 0x4D, raw[4:6]==00 09; raw[8]==0xFF 表示设备忙需重试;
        连接状态=raw[18], 充电=raw[19], 电量=raw[20]
  实测: 电量 0x64=100, 与 MCHOSE 官方 M HUB 显示一致; connect=2 即 2.4G

键盘 K99 V3（2.4G 接收器 PID 0x3033）——协议已逆向（tools/ 留有完整抓包）:
  命令通道: usagePage 0x0001 / usage 0x0000 集合, output report 无编号(0x00 前缀)
  Z 帧: [0x55, cmd, 0x00, cs, size, offLo, offHi, 0x00, ...data]
        cs = size^offLo^offHi^0x00; 应答 [0xAA, cmd, 0x00, len, size, offLo, offHi, 0, data...]
  电量无查询命令, 由键盘异步推送(事件驱动, 无固定周期):
        FA FB 07 <电量%> <充电标志>                       (老通道广播)
        [AA 07 00 len size offLo offHi 00 掩码Lo 掩码Hi 充电 电量 ...]  (MANUAL_REPORT)
  因此 KeyboardListener 常驻监听, 最近数值落盘缓存。
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

import hid

import log

log.get_logger("battery")  # 初始化根配置
log_ = log.get_logger("battery.read")

# 图形界面程序调用控制台子进程时禁止弹出黑窗
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

VID = 0x3837
MOUSE_PID_DONGLE = 0x1014
KBD_PID_DONGLE = 0x3033

_CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MCHOSEBattery")
_KB_CACHE_FILE = os.path.join(_CACHE_DIR, "keyboard.json")


# ---------------- 纯解析函数(可单测) ----------------
def mouse_query_frame():
    """鼠标 0x0900 电量查询帧: 0x4D 前缀 + M 帧 + 零填充至 64 字节。"""
    body = bytearray([0x01, 0x01, 0x00, 0x00, 0x09, 0x00, 0x00])
    cs = 0
    for x in body[1:]:
        cs ^= x
    body.append(cs)
    report = bytes([0x4D]) + bytes(body)
    return report + b"\x00" * (64 - len(report))


def parse_mouse_reply(raw):
    """鼠标 0x0900 回复 -> dict | None。"""
    if len(raw) < 21 or raw[0] != 0x4D or raw[4] != 0x00 or raw[5] != 0x09:
        return None
    if raw[8] == 0xFF:  # 设备忙
        return None
    return {
        "percent": raw[20],
        "charging": raw[19] != 0,
        "connect": {2: "2.4G"}.get(raw[18], f"mode{raw[18]}"),
        "source": "dongle",
    }


def parse_legacy_battery(raw):
    """FA FB 07 老通道电量广播 -> (percent, charging) | None。"""
    if len(raw) > 4 and raw[0] == 0xFA and raw[1] == 0xFB and raw[2] == 0x07:
        if 0 <= raw[3] <= 100:
            return raw[3], raw[4] != 0
    return None


def parse_manual_report(raw):
    """MANUAL_REPORT 推送 (Z 帧广播, 命令 0x0700) -> (percent, charging) | None。
    data[2]=充电(0/1/2) data[3]=电量% data[4]=连接(1有线/2无线)。"""
    if len(raw) > 11 and raw[0] == 0xAA and raw[1] == 0x07 and raw[2] == 0x00:
        charge, percent = raw[10], raw[11]
        if 0 <= percent <= 100:
            return percent, charge == 1
    return None


def match_device_name(friendly_name):
    """蓝牙 FriendlyName -> "mouse" | "keyboard" | None。"""
    n = (friendly_name or "").lower()
    if "k7" in n:
        return "mouse"
    if "k99" in n:
        return "keyboard"
    return None


# ---------------- 蓝牙模式 ----------------
# 判在线分两级:
#   1) HID-over-GATT 集合 (HID\{00001812*}) PresentOnly 存在 = 链路活跃, 直接可信;
#   2) 集合不在场 = 蓝牙闲置省电断链(非拔配对): LastConnectedTime 在 24 小时内
#      仍使用电量属性缓存值(断链期间固件近乎不放电, 缓存偏差很小)。
_PS_BLE = r"""
$all = Get-PnpDevice -PresentOnly
$hids = @($all | Where-Object { $_.InstanceId -like 'HID\{00001812*' })
foreach ($h in $hids) {
  if ($h.InstanceId -match 'VID&..([0-9A-F]{4})_PID&([0-9A-F]{4})_REV&[0-9A-F]{4}_([0-9A-F]{12})') {
    $mac = $matches[3]
    $dev = $all | Where-Object { $_.InstanceId -like ('BTHLE\DEV_' + $mac + '*') } | Select-Object -First 1
    if ($dev) {
      $b = Get-PnpDeviceProperty -InstanceId $dev.InstanceId -KeyName '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction SilentlyContinue
      if ($b -and $null -ne $b.Data) { Write-Output ('name=' + $dev.FriendlyName + '|bat=' + [int]$b.Data + '|hid=1') }
    }
  }
}
foreach ($dev in ($all | Where-Object { $_.InstanceId -like 'BTHLE\DEV_*' })) {
  $mac = $dev.InstanceId.Split('\')[1].Replace('DEV_', '')
  $online = $false
  foreach ($h in $hids) { if ($h.InstanceId -like ('*' + $mac + '*')) { $online = $true } }
  if (-not $online) {
    $b = Get-PnpDeviceProperty -InstanceId $dev.InstanceId -KeyName '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction SilentlyContinue
    $lc = Get-PnpDeviceProperty -InstanceId $dev.InstanceId -KeyName 'DEVPKEY_Bluetooth_LastConnectedTime' -ErrorAction SilentlyContinue
    if ($b -and $null -ne $b.Data -and $lc -and $null -ne $lc.Data) {
      $lcVal = $lc.Data
      if ($lcVal -is [DateTime]) { $age = [int][Math]::Abs(((Get-Date) - $lcVal).TotalSeconds) }
      else { $age = [int][Math]::Abs(((Get-Date) - [DateTime]::FromFileTime([int64]$lcVal)).TotalSeconds) }
      if ($age -lt 86400) { Write-Output ('name=' + $dev.FriendlyName + '|bat=' + [int]$b.Data + '|hid=0|age=' + $age) }
    }
  }
}
"""

_ble_cache = {"ts": 0.0, "data": {"mouse": None, "keyboard": None,
                                  "mouse_live": False, "keyboard_live": False}}
BLE_TTL = 120  # 秒; PS 扫描单次 2~5 秒 CPU, 拉长间隔降低占用


def ble_batteries(max_age=BLE_TTL):
    """蓝牙 MCHOSE 设备电量。返回 dict:
    mouse/keyboard = 百分比|None; *_live = True 表示 BLE 链路硬在线(实时可信),
    False 表示闲置断链的 GATT 缓存(24 小时内连接过)。"""
    now = time.monotonic()
    if now - _ble_cache["ts"] < max_age:
        return _ble_cache["data"]
    data = {"mouse": None, "keyboard": None, "mouse_live": False, "keyboard_live": False}
    t0 = time.monotonic()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_BLE],
                           capture_output=True, text=True, timeout=40,
                           encoding="mbcs", errors="replace",
                           creationflags=_CREATE_NO_WINDOW)
        for line in (r.stdout or "").splitlines():
            m = re.match(r"name=(.*)\|bat=(\d+)\|hid=(\d)(?:\|age=(\d+))?", line.strip())
            if not m:
                continue
            dev = match_device_name(m.group(1))
            bat, live = int(m.group(2)), m.group(3) == "1"
            if dev:
                data[dev], data[dev + "_live"] = bat, live
    except (OSError, subprocess.TimeoutExpired):
        log_.warning("BLE 扫描失败/超时")
    log_.debug("BLE 扫描耗时 %.1fs: %s", time.monotonic() - t0, data)
    _ble_cache["ts"] = now
    _ble_cache["data"] = data
    return data


def read_mouse(attempts=3):
    """鼠标电量: 2.4G 接收器实时查询优先(带充电标志), 查询不到再读蓝牙电量属性。"""
    infos = [d for d in hid.enumerate(VID, MOUSE_PID_DONGLE)
             if d["usage_page"] == 0xFF01 and d["usage"] == 0x0001]
    frame = mouse_query_frame()
    for _ in range(attempts if infos else 0):
        try:
            dev = hid.device()
            dev.open_path(infos[0]["path"])
        except OSError as e:
            log_.debug("鼠标集合打开失败: %s", e)
            break
        try:
            dev.set_nonblocking(True)
            dev.write(frame)
            end = time.monotonic() + 0.3
            while time.monotonic() < end:
                data = dev.read(64, timeout_ms=0)
                if not data:
                    time.sleep(0.005)  # 避免忙等待空转 CPU
                    continue
                st = parse_mouse_reply(bytes(data))
                if st:
                    return st
        except OSError as e:
            log_.debug("鼠标查询 IO 错误: %s", e)
            break
        finally:
            dev.close()
        time.sleep(0.15)
    # 2.4G 查询不到(接收器未插/鼠标不在接收器链路上) → 蓝牙电量属性兜底
    bt = ble_batteries().get("mouse")
    if bt is not None:
        return {"percent": bt, "charging": False, "connect": "蓝牙", "source": "ble"}
    return None


class KeyboardListener(threading.Thread):
    """常驻监听 K99 V3 键盘的电量推送帧。
    外层守卫保证任何异常都不会永久杀死线程(3 秒后重开设备)。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.percent = None
        self.charging = None
        self.ts = 0.0          # 最近一次推送的 unix 时间
        self.connected = None  # FA FB 06 广播: True=通信开始
        self.pushes = 0        # 会话内收到的电量推送数(诊断用)
        self._stop = False
        self._load_cache()

    # ---- 缓存 ----
    def _load_cache(self):
        try:
            with open(_KB_CACHE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            self.percent = d.get("percent")
            self.charging = d.get("charging")
            self.ts = d.get("ts", 0.0)
            log_.info("键盘缓存载入: %s%% (%s)", self.percent, time.strftime("%m-%d %H:%M", time.localtime(self.ts)))
        except (OSError, ValueError):
            pass

    def _save_cache(self):
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(_KB_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"percent": self.percent, "charging": self.charging, "ts": self.ts}, f)
        except OSError:
            pass

    # ---- 解析 ----
    def _feed(self, raw):
        parsed = parse_legacy_battery(raw)
        if parsed:
            self._apply(*parsed)
            return
        if raw[0] == 0xFA and raw[1] == 0xFB and raw[2] == 0x06:  # 链路建立/断开 = 切模式信号
            online = raw[3] == 0
            if self.connected is not None and self.connected != online:
                _ble_cache["ts"] = 0.0  # 立即作废蓝牙扫描缓存, 下轮轮询即可反映新模式
                log_.info("键盘链路%s, 已作废蓝牙缓存", "建立" if online else "断开")
            self.connected = online
            return
        parsed = parse_manual_report(raw)
        if parsed:
            self._apply(*parsed)
            log_.debug("MANUAL_REPORT: %s%% charging=%s", *parsed)

    def _apply(self, percent, charging):
        self.percent = percent
        self.charging = charging
        self.ts = time.time()
        self.pushes += 1
        self._save_cache()
        log_.info("键盘电量推送 #%d: %d%% charging=%s", self.pushes, percent, charging)

    # ---- 线程 ----
    def run(self):
        while not self._stop:
            try:
                self._run_once()
            except Exception:
                log_.exception("键盘监听线程异常, 3 秒后重启")
                time.sleep(3)

    def _run_once(self):
        warmups = (bytes([0x55, 0x03, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00]),
                   bytes([0x55, 0x04, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00]))
        while not self._stop:
            dev = None
            try:
                info = next((i for i in hid.enumerate(VID, KBD_PID_DONGLE)
                             if i["usage_page"] == 0x0001 and i["usage"] == 0x0000), None)
                if info is None:
                    time.sleep(3)
                    continue
                dev = hid.device()
                dev.open_path(info["path"])
                dev.set_nonblocking(True)
                log_.debug("键盘监听: 设备已打开")
                for f in warmups:  # 唤醒命令通道(复刻官方首命令)
                    dev.write(bytes([0x00]) + f + b"\x00" * 55)
                    time.sleep(0.15)
                t0 = time.monotonic()
                while time.monotonic() - t0 < 1.0:
                    dev.read(64, timeout_ms=0)
                idle = 0.0
                while not self._stop:
                    try:
                        data = dev.read(64, timeout_ms=250)
                    except OSError:
                        break
                    if data:
                        idle = 0.0
                        self._feed(bytes(data))
                    else:
                        idle += 0.25
                        if idle >= 600:  # 每 10 分钟重发握手, 刺激固件回报状态(若有)
                            idle = 0.0
                            try:
                                for f in warmups:
                                    dev.write(bytes([0x00]) + f + b"\x00" * 55)
                                    time.sleep(0.05)
                            except OSError:
                                break
            except OSError:
                time.sleep(3)
            finally:
                if dev:
                    try:
                        dev.close()
                    except OSError:
                        pass

    def stop(self):
        self._stop = True


_kb_listener = None


def start_keyboard_listener():
    global _kb_listener
    if _kb_listener is None:
        _kb_listener = KeyboardListener()
        _kb_listener.start()
        log_.info("键盘推送监听已启动")
    return _kb_listener


def read_keyboard():
    """键盘电量: 蓝牙硬在线(实时查询) > 2.4G 推送监听 > 蓝牙闲置缓存。
    蓝牙硬在线必须最优先且仅它优先——键盘切回 2.4G 后集合消失,
    闲置缓存不得覆盖推送监听刚拿到的 2.4G 数据。"""
    ble = ble_batteries()
    if ble["keyboard"] is not None and ble["keyboard_live"]:
        return {"percent": ble["keyboard"], "charging": False, "age": None,
                "connect": "蓝牙", "source": "ble"}
    if _kb_listener is None:
        start_keyboard_listener()
    if _kb_listener.percent is not None:
        return {
            "percent": _kb_listener.percent,
            "charging": bool(_kb_listener.charging),
            "age": time.time() - _kb_listener.ts if _kb_listener.ts else None,
            "connect": "2.4G",
            "source": "push",
        }
    if ble["keyboard"] is not None:
        return {"percent": ble["keyboard"], "charging": False, "age": None,
                "connect": "蓝牙", "source": "ble"}
    return None


if __name__ == "__main__":
    print("鼠标:", read_mouse())
    print("键盘:", read_keyboard())
