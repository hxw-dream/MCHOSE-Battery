"""MCHOSE 电量托盘程序。

托盘图标实时显示鼠标电量(数字直接画在图标上), 悬停看详情, 低电量弹通知。
键盘电量: 2.4G 协议待破解, 当前显示 "--"; 键盘切蓝牙模式时自动改读蓝牙属性。

用法:
    python tray_app.py            # 正常启动(建议用 pythonw 运行, 无控制台)
    python tray_app.py --selftest # 只读一次电量打印后退出
    python tray_app.py --smoke    # 启动托盘 5 秒后自动退出(冒烟测试)
"""
import sys
import threading
import time
import winreg

import pystray
from PIL import Image, ImageDraw, ImageFont

import battery

POLL_SECONDS = 5
LOW_BATTERY = 20

FONT_CANDIDATES = [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\msyh.ttc"]


def _font(size):
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def draw_icon(percent, charging=False):
    """电量数字托盘图标: 绿>50 橙20-50 红<=20, 未知灰色 --。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if percent is None:
        color, text, size = (120, 120, 120, 255), "--", 26
    else:
        color = ((76, 175, 80, 255) if percent > 50 else
                 (255, 152, 0, 255) if percent > LOW_BATTERY else
                 (244, 67, 54, 255))
        text, size = str(percent), (24 if percent >= 100 else 30)
    d.ellipse([2, 2, 62, 62], fill=color)
    if charging:
        d.polygon([(36, 10), (22, 36), (31, 36), (28, 54), (42, 28), (33, 28)], fill=(255, 255, 255, 255))
        box = [10, 14, 54, 50]
    else:
        box = [4, 8, 60, 56]
    f = _font(size)
    bx0, by0, bx1, by1 = d.textbbox((0, 0), text, font=f)
    x = (box[0] + box[2]) / 2 - (bx1 - bx0) / 2
    y = (box[1] + box[3]) / 2 - (by1 - by0) / 2 - by0
    d.text((x, y), text, font=f, fill=(255, 255, 255, 255))
    return img


class App:
    def __init__(self):
        self.state = {"mouse": None, "keyboard": None, "ts": 0.0}
        self.low_notified = False
        self.notify_enabled = True
        self.icon = pystray.Icon(
            "MCHOSE", icon=draw_icon(None), title="MCHOSE 电量读取中…",
            menu=pystray.Menu(
                pystray.MenuItem("立即刷新", lambda *_: self.refresh(), default=True),
                pystray.MenuItem("低电量提醒", self._toggle_notify, checked=lambda *_: self.notify_enabled),
                pystray.MenuItem("开机自启", self._toggle_autostart, checked=lambda *_: autostart_enabled()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            ))

    # ---- 菜单动作 ----
    def _toggle_notify(self, *_):
        self.notify_enabled = not self.notify_enabled

    def _toggle_autostart(self, *_):
        set_autostart(not autostart_enabled())

    def _quit(self, *_):
        self.icon.stop()

    # ---- 核心 ----
    def refresh(self):
        try:
            self.state["mouse"] = battery.read_mouse()
        except Exception:
            self.state["mouse"] = None
        try:
            self.state["keyboard"] = battery.read_keyboard()
        except Exception:
            self.state["keyboard"] = None
        self.state["ts"] = time.monotonic()
        self._update_ui()
        self._low_battery_check()

    def _fmt(self, st, name):
        if st is None or st.get("percent") is None:
            extra = "（等待电量推送）" if name == "键盘" else ""
            return f"{name} --{extra}"
        extra = " ⚡充电中" if st.get("charging") else ""
        age = st.get("age")
        if age and age > 90:
            extra += f"（{age/60:.0f} 分钟前推送）" if age < 3600 else "（1 小时前推送）"
        return f"{name} {st['percent']}% ({st.get('connect', '?')}){extra}"

    def _update_ui(self):
        m = self.state["mouse"]
        percent = m["percent"] if m else None
        charging = bool(m and m.get("charging"))
        self.icon.icon = draw_icon(percent, charging)
        self.icon.title = "MCHOSE 电量\n" + "\n".join([
            self._fmt(m, "鼠标"),
            self._fmt(self.state["keyboard"], "键盘"),
        ])

    def _low_battery_check(self):
        m = self.state["mouse"]
        if not self.notify_enabled or m is None:
            return
        p = m["percent"]
        if p <= LOW_BATTERY and not self.low_notified:
            self.low_notified = True
            try:
                self.icon.notify(f"鼠标电量 {p}%，请及时充电", "MCHOSE 低电量提醒")
            except Exception:
                pass
        elif p > LOW_BATTERY + 5:
            self.low_notified = False

    def loop(self):
        while True:
            self.refresh()
            time.sleep(POLL_SECONDS)

    def run(self):
        threading.Thread(target=self.loop, daemon=True).start()
        self.icon.run()


# ---- 开机自启 (HKCU Run) ----
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "MCHOSE Battery"


def _autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    script = sys.argv[0]
    return f'"{pythonw}" "{script}"'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(enable):
    try:
        if enable:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
                winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, _RUN_NAME)
    except OSError:
        pass


def main():
    battery.start_keyboard_listener()  # 键盘电量推送常驻监听
    app = App()
    if "--selftest" in sys.argv:
        app.refresh()
        m, k = app.state["mouse"], app.state["keyboard"]
        print("鼠标:", m)
        print("键盘:", k)
        print("图标渲染:", "OK" if draw_icon(85) else "FAIL")
        return
    if "--smoke" in sys.argv:
        threading.Thread(target=lambda: (time.sleep(5), app._quit()), daemon=True).start()
        app.run()
        print("smoke ok")
        return
    app.run()


if __name__ == "__main__":
    main()
