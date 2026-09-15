"""桌面电量浮窗: 暗色玻璃卡片, 每设备一行"电池外形"进度条。

- tkinter 无边框置顶窗口, 透明色抠出圆角
- 按系统 DPI 缩放系数渲染 (高分屏不缩小), Pillow 高倍率绘制
- 拖动移动(位置记忆), 右键隐藏, 托盘可再显示
- 后台线程轮询共享 state dict, 仅在数据变化时重绘
"""
import ctypes
import json
import os
import threading

import tkinter as tk

from PIL import Image, ImageDraw, ImageTk, ImageFont

_CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MCHOSEBattery")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "widget.json")

# ---- 设计令牌 (逻辑像素, 运行时乘以 dpi 缩放) ----
CARD_W, CARD_H = 330, 104
PAD = 17
BG = (23, 25, 30, 255)
STROKE = (42, 45, 53, 255)
TRACK = (38, 41, 50, 255)
TEXT = (232, 234, 237, 255)
DIM = (139, 144, 155, 255)
GREEN = (61, 214, 140, 255)
AMBER = (245, 184, 65, 255)
RED = (244, 87, 77, 255)
KEY = (255, 0, 254)  # 透明抠除色

_FONT_CACHE = {}


def _font(kind, scale):
    key = (kind, scale)
    if key not in _FONT_CACHE:
        try:
            if kind == "num":
                f = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 22 * scale)
            elif kind == "label":
                f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 14 * scale)
            else:
                f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 11 * scale)
        except OSError:
            f = ImageFont.load_default()
        _FONT_CACHE[key] = f
    return _FONT_CACHE[key]


def _level_color(percent, charging):
    if charging:
        return GREEN
    if percent is None:
        return TRACK
    return GREEN if percent > 50 else AMBER if percent > 20 else RED


def _draw_bolt(draw, cx, cy, s, fill):
    """小闪电: 以 (cx,cy) 为中心, s 为半高。"""
    pts = [(cx - s * 0.18, cy - s), (cx + s * 0.30, cy - s * 0.12),
           (cx + s * 0.05, cy - s * 0.12), (cx + s * 0.18, cy + s),
           (cx - s * 0.30, cy + s * 0.08), (cx - s * 0.04, cy + s * 0.08)]
    draw.polygon(pts, fill=fill)


def render_card(state, scale=2):
    """state: {"mouse": st|None, "keyboard": st|None} -> PIL.Image (逻辑尺寸 x scale)"""
    f_num, f_label, f_dim = (_font(k, scale) for k in ("num", "label", "dim"))
    img = Image.new("RGBA", (CARD_W * scale, CARD_H * scale), KEY)
    d = ImageDraw.Draw(img)
    box = [scale, scale, (CARD_W - 2) * scale, (CARD_H - 2) * scale]
    d.rounded_rectangle(box, radius=11 * scale, fill=BG)
    d.rounded_rectangle(box, radius=11 * scale, outline=STROKE, width=scale)

    rows = [("鼠标", state.get("mouse")), ("键盘", state.get("keyboard"))]
    row_h = (CARD_H - 2 * PAD) / 2
    for i, (label, st) in enumerate(rows):
        cy = (PAD + i * row_h + row_h / 2) * scale  # 行中心
        st = st or {}
        percent = st.get("percent")
        charging = bool(st.get("charging"))
        connect = st.get("connect") or ("等待推送" if label == "键盘" else "")
        color = _level_color(percent, charging)

        # 左侧: 设备名 + 连接方式
        d.text((PAD * scale, cy - 16 * scale), label, font=f_label, fill=TEXT)
        d.text((PAD * scale, cy + 3 * scale), connect, font=f_dim, fill=DIM)

        # 中间: 电池外形进度条 (轨道 148x11 + 正极凸头)
        bar_x, bar_w, bar_h = 68, 150, 11
        by = cy - bar_h * scale / 2
        d.rounded_rectangle([bar_x * scale, by, (bar_x + bar_w) * scale, by + bar_h * scale],
                            radius=bar_h * scale / 2, fill=TRACK)
        nub_w, nub_h = 3, bar_h + 6
        d.rounded_rectangle([(bar_x + bar_w + 2) * scale, cy - nub_h * scale / 2,
                             (bar_x + bar_w + 2 + nub_w) * scale, cy + nub_h * scale / 2],
                            radius=nub_w * scale / 2, fill=TRACK)
        if percent is not None and percent > 0:
            fw = max(bar_h, int(bar_w * min(percent, 100) / 100))
            d.rounded_rectangle([bar_x * scale, by, (bar_x + fw) * scale, by + bar_h * scale],
                                radius=bar_h * scale / 2, fill=color)
        if charging:
            _draw_bolt(d, (bar_x + bar_w - 12) * scale, cy, 9 * scale, (255, 255, 255, 235))

        # 右侧: 百分比
        txt = "--" if percent is None else f"{percent}%"
        bbox = d.textbbox((0, 0), txt, font=f_num)
        tw = bbox[2] - bbox[0]
        d.text(((CARD_W - PAD) * scale - tw, cy - (bbox[3] - bbox[1]) / 2 - bbox[1]), txt,
               font=f_num, fill=TEXT if percent is not None else DIM)
    return img


def _load_config():
    try:
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


class Widget:
    def __init__(self, state_getter, flags):
        self.state_getter = state_getter
        self.flags = flags  # {"visible": bool} 由托盘线程读写
        cfg = _load_config()
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self.last_sig = None
        self._init_tk()

    def _init_tk(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        self.tk = tk.Tk()
        self.tk.overrideredirect(True)
        self.tk.attributes("-topmost", True)
        self.tk.configure(bg=f"#{KEY[0]:02x}{KEY[1]:02x}{KEY[2]:02x}")
        try:
            self.tk.attributes("-transparentcolor", f"#{KEY[0]:02x}{KEY[1]:02x}{KEY[2]:02x}")
        except tk.TclError:
            pass
        # 系统缩放系数: 高分屏按比例放大, 字与图形同步变大
        try:
            dpi = self.tk.winfo_fpixels("1i")
        except tk.TclError:
            dpi = 96
        self.scale = max(1, round(dpi / 96))
        w, h = CARD_W * self.scale, CARD_H * self.scale
        sw = self.tk.winfo_screenwidth()
        sh = self.tk.winfo_screenheight()
        x = int(self.cfg.get("x", sw - w - 30))
        y = int(self.cfg.get("y", sh - h - 90))
        self.tk.geometry(f"{w}x{h}+{x}+{y}")
        self.tk.resizable(False, False)

        self.label = tk.Label(self.tk, bd=0, bg=f"#{KEY[0]:02x}{KEY[1]:02x}{KEY[2]:02x}")
        self.label.pack()
        self.label.bind("<Button-1>", self._drag_start)
        self.label.bind("<B1-Motion>", self._drag_move)
        self.label.bind("<ButtonRelease-1>", self._drag_end)
        self.label.bind("<Button-3>", self._popup_menu)
        self.menu = tk.Menu(self.tk, tearoff=0)
        self.menu.add_command(label="隐藏浮窗", command=self.hide)

        self._apply_visibility()
        self.tk.after(400, self._tick)

    # ---- 托盘控制的可见性 ----
    def _apply_visibility(self):
        if self.flags.get("visible", True):
            self.tk.deiconify()
        else:
            self.tk.withdraw()

    def hide(self):
        self.flags["visible"] = False
        self.cfg["hidden"] = True
        save_config(self.cfg)
        self._apply_visibility()

    def show(self):
        self.flags["visible"] = True
        self.cfg["hidden"] = False
        save_config(self.cfg)
        self._apply_visibility()

    # ---- 拖动 ----
    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        x = self.tk.winfo_x() + e.x - self._dx
        y = self.tk.winfo_y() + e.y - self._dy
        self.tk.geometry(f"+{x}+{y}")

    def _drag_end(self, e):
        sw = self.tk.winfo_screenwidth()
        sh = self.tk.winfo_screenheight()
        x = max(-CARD_W * self.scale // 2, min(self.tk.winfo_x(), sw - 20))
        y = max(0, min(self.tk.winfo_y(), sh - 40))
        self.tk.geometry(f"+{x}+{y}")
        self.cfg["x"], self.cfg["y"] = x, y
        save_config(self.cfg)

    def _popup_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    # ---- 数据轮询与重绘 ----
    def _tick(self):
        state = self.state_getter() or {}
        m, k = state.get("mouse"), state.get("keyboard")
        sig = tuple((s or {}).get(k2) for s, k2 in
                    ((m, "percent"), (m, "charging"), (m, "connect"),
                     (k, "percent"), (k, "charging"), (k, "connect")))
        if sig != self.last_sig:
            self.last_sig = sig
            img = render_card({"mouse": m, "keyboard": k}, self.scale)
            self._photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self._photo)
        vis = self.flags.get("visible", True)
        if vis and not self.tk.winfo_viewable():
            self._apply_visibility()
        elif not vis and self.tk.winfo_viewable():
            self._apply_visibility()
        self.tk.after(1000, self._tick)

    def run(self):
        self.tk.mainloop()


def run_widget(state_getter, flags):
    """线程入口: state_getter() 返回托盘共享 state; flags["visible"] 控制显隐。"""
    try:
        Widget(state_getter, flags).run()
    except Exception:
        pass  # 浮窗失败不影响托盘


if __name__ == "__main__":
    demo = {"mouse": {"percent": 91, "charging": False, "connect": "2.4G"},
            "keyboard": {"percent": 70, "charging": True, "connect": "蓝牙"}}
    run_widget(lambda: demo, {"visible": True})
