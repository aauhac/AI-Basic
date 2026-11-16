"""OS-level window capture and input for the real-play demo (Windows only).

* Capture: Win32 PrintWindow on the game's own top-level windows only (no desktop/other apps).
* Input:   Win32 SendInput -- the same path a physical keyboard/mouse uses. Every input is sent
           only after checking that the foreground window belongs to the game process; otherwise
           the demo aborts, so keystrokes can never land in another application.
Nothing here touches the game's Python objects: the game runs in a separate process.
"""
import ctypes
import time
from ctypes import wintypes

import numpy as np

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32
ULONG_PTR = ctypes.c_size_t

PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
SWP_NOZORDER, SWP_NOACTIVATE = 0x4, 0x10
DWMWA_EXTENDED_FRAME_BOUNDS = 9


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _U)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

VK = {'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28, 'space': 0x20, 'escape': 0x1B,
      'alt': 0x12, 'f4': 0x73}
EXTENDED = {'left', 'up', 'right', 'down'}
for _c in 'abcdefghijklmnopqrstuvwxyz':
    VK[_c] = ord(_c.upper())


class FocusLost(RuntimeError):
    pass


# ----------------------------------------------------------------------------- windows
def windows_of_pid(pid):
    """Visible top-level windows of a process, in z-order (topmost first)."""
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                out.append(hwnd)
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def pid_of(hwnd):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def frame_bounds(hwnd):
    """Visible window rectangle (without the invisible Win10/11 resize border)."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def window_rect(hwnd):
    r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def client_origin(hwnd):
    pt = wintypes.POINT(0, 0); user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def set_client_size(hwnd, x, y, cw, ch):
    """Resize like a user dragging the border: outer size chosen so the client area is cw x ch."""
    l, t, r, b = window_rect(hwnd)
    cr = wintypes.RECT(); user32.GetClientRect(hwnd, ctypes.byref(cr))
    dw = (r - l) - cr.right; dh = (b - t) - cr.bottom
    user32.SetWindowPos(hwnd, 0, x, y, cw + dw, ch + dh, SWP_NOZORDER)


def is_foreground_ours(pid):
    fg = user32.GetForegroundWindow()
    return bool(fg) and pid_of(fg) == pid


def bring_to_front(hwnd):
    user32.ShowWindow(hwnd, 9)                        # SW_RESTORE
    fg = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = fg_thread and fg_thread != cur and user32.AttachThreadInput(cur, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur, fg_thread, False)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


# ----------------------------------------------------------------------------- capture
def grab_window(hwnd):
    """RGB numpy image of the whole visible window (title bar included) via PrintWindow."""
    if user32.IsIconic(hwnd):
        return None
    l, t, r, b = window_rect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT):
            return None
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0):
            return None
        a = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, 2::-1]
    finally:
        gdi32.SelectObject(mdc, old); gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(hwnd, hdc)
    fl, ft, fr, fb = frame_bounds(hwnd)                  # crop invisible borders
    return np.ascontiguousarray(a[ft - t:fb - t, fl - l:fr - l])


def cursor_pos():
    pt = wintypes.POINT(); user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ----------------------------------------------------------------------------- input
class Input:
    """SendInput wrapper bound to one game process; refuses to type into any other window."""

    def __init__(self, pid, log):
        self.pid = pid
        self.log = log            # callable(kind, value)
        self.main_hwnd = None

    def set_pid(self, pid, main_hwnd=None):
        self.pid = pid
        self.main_hwnd = main_hwnd

    def guard(self):
        if is_foreground_ours(self.pid):
            return
        fg = user32.GetForegroundWindow()
        cls = ctypes.create_unicode_buffer(64)
        if fg:
            user32.GetClassNameW(fg, cls, 64)
        if self.main_hwnd and bring_to_front(self.main_hwnd) and is_foreground_ours(self.pid):
            self.log('refocus', cls.value)          # class name only (no window titles of other apps)
            return
        raise FocusLost('게임 창이 전면에 없습니다 -- 다른 앱으로 입력이 가지 않도록 중단합니다.')

    @staticmethod
    def _key_input(name, up):
        vk = VK[name]
        flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if name in EXTENDED else 0)
        scan = user32.MapVirtualKeyW(vk, 0)
        i = INPUT(type=INPUT_KEYBOARD)
        i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return i

    def _send(self, *inputs):
        arr = (INPUT * len(inputs))(*inputs)
        n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if n != len(inputs):
            raise OSError(f'SendInput failed: {ctypes.get_last_error()}')

    def key_down(self, name, label=None):
        self.guard(); self._send(self._key_input(name, False))
        self.log('key', label or name)

    def key_up(self, name):
        self._send(self._key_input(name, True))

    def tap(self, name, hold=0.03, label=None):
        self.key_down(name, label)
        time.sleep(hold)
        self.key_up(name)

    def combo(self, mod, name):
        self.guard()
        self._send(self._key_input(mod, False)); time.sleep(0.03)
        self._send(self._key_input(name, False)); time.sleep(0.03)
        self._send(self._key_input(name, True), self._key_input(mod, True))
        self.log('key', f'{mod}+{name}')

    def move_mouse(self, x, y, duration=0.35):
        sx, sy = cursor_pos()
        n = max(1, int(duration / 0.015))
        for k in range(1, n + 1):
            t = k / n; e = t * t * (3 - 2 * t)
            user32.SetCursorPos(int(sx + (x - sx) * e), int(sy + (y - sy) * e))
            time.sleep(duration / n)

    def click(self, x, y, label=''):
        self.move_mouse(x, y)
        time.sleep(0.12)
        self.guard()
        a = INPUT(type=INPUT_MOUSE); a.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
        b = INPUT(type=INPUT_MOUSE); b.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
        self._send(a); time.sleep(0.06); self._send(b)
        self.log('click', label)
