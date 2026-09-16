"""自绘系统托盘图标 (ctypes Shell_NotifyIcon), 替代 pystray 以支持全自定义菜单。

- 独立线程: 消息窗口 + GetMessage 循环
- 左键 -> on_left 回调; 右键 -> on_right(x, y) 回调 (坐标为光标物理位置)
- update(icon_pil, tip) 更新图标与悬停提示; notify(title, msg) 气泡通知
- stop() 摘除图标并结束线程
"""
import ctypes
import io
import threading
from ctypes import wintypes

_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_kernel32 = ctypes.windll.kernel32

WM_APP_TRAY = 0x8001
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 16


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID), ("hBalloonIcon", wintypes.HANDLE),
    ]


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", wintypes.WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


def _pil_to_hicon(img):
    """PIL Image -> HICON (内嵌 16/32/48 三档)。"""
    buf = io.BytesIO()
    img.save(buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    data = buf.getvalue()
    return _user32.CreateIconFromResourceEx(data, len(data), True, 0x00030000, 32, 32, 0)


class TrayIcon:
    """on_left()/on_right(x, y) 在托盘线程回调; notify/update 可跨线程调用。"""

    def __init__(self, tip, on_left, on_right):
        self.tip = tip
        self.on_left = on_left
        self.on_right = on_right
        self.hwnd = None
        self._hicon = None
        self._thread = None
        self._wndproc_ref = None
        self._ready = threading.Event()

    # ---- 生命周期 ----
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self):
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(3)

    def _run(self):
        hinst = _kernel32.GetModuleHandleW(None)
        proc = wintypes.WNDPROC(self._wndproc)
        self._wndproc_ref = proc  # 防 GC
        wc = _WNDCLASSW()
        wc.lpfnWndProc = proc
        wc.lpszClassName = "MCHOSEBatteryTray"
        wc.hInstance = hinst
        _user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = _user32.CreateWindowExW(0, wc.lpszClassName, "MCHOSEBatteryTray",
                                            0, 0, 0, 0, 0, None, None, hinst, None)
        self._add_icon()
        self._ready.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        self._delete_icon()

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_APP_TRAY:
                if lp == WM_LBUTTONUP and self.on_left:
                    self.on_left()
                elif lp == WM_RBUTTONUP and self.on_right:
                    pt = wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    self.on_right(pt.x, pt.y)
                return 0
            if msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return _user32.DefWindowProcW(hwnd, msg, wp, lp)

    # ---- 图标 / 提示 / 气泡 ----
    def _add_icon(self):
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.szTip = self.tip[:127]
        _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _delete_icon(self):
        if not self.hwnd:
            return
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def update(self, icon_img=None, tip=None):
        """更新图标(PIL Image)与悬停文字, 可在任意线程调用。"""
        if not self.hwnd:
            return
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = 0
        if icon_img is not None:
            hicon = _pil_to_hicon(icon_img)
            if hicon:
                if self._hicon:
                    _user32.DestroyIcon(self._hicon)
                self._hicon = hicon
                nid.uFlags |= NIF_ICON
                nid.hIcon = hicon
        if tip is not None:
            self.tip = tip
            nid.uFlags |= NIF_TIP
            nid.szTip = tip[:127]
        if nid.uFlags:
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def notify(self, title, msg):
        if not self.hwnd:
            return
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_INFO
        nid.szInfo = msg[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = 1  # NIIF_INFO
        _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
