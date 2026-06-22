"""窗口控制模块"""

# ruff: noqa: E402

import ctypes
import time
from ctypes import wintypes
import pyautogui
from bot.comtypes_cache import configure_comtypes_cache

configure_comtypes_cache()
import uiautomation as auto
import psutil
from loguru import logger

user32 = ctypes.windll.user32
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.IsIconic.restype = ctypes.c_bool
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.restype = ctypes.c_bool
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.MoveWindow.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_bool,
]
user32.MoveWindow.restype = ctypes.c_bool

MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    fields = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


_switch_to_this_window = getattr(user32, "SwitchToThisWindow", None)
if _switch_to_this_window:
    _switch_to_this_window.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    _switch_to_this_window.restype = None


def _timeout_call(func, default=None, timeout_ms=3000):
    """带超时的Windows API调用，防止阻塞"""
    import threading

    result = [default]
    finished = threading.Event()

    def wrapper():
        try:
            result[0] = func()
        except Exception:
            result[0] = default
        finally:
            finished.set()

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    t.join(timeout=timeout_ms / 1000)
    if finished.is_set():
        return result[0]
    return default


def send_hotkey(*keys):
    """发送热键"""
    for key in keys:
        pyautogui.keyDown(key)
    time.sleep(0.05)
    for key in keys:
        pyautogui.keyUp(key)
    time.sleep(0.05)


class WindowController:
    """窗口控制类"""

    def __init__(self, wx_window=None):
        self.wx_window = wx_window
        self.current_chat = ""

    def _looks_mojibake(self, text: str) -> bool:
        """判断会话名是否像乱码，避免把回复粘到搜索框。"""
        if not text:
            return False
        suspicious_tokens = ("�", "Ã", "Â", "ð", "þ", "\ufffd")
        return any(token in text for token in suspicious_tokens)

    def focus_chat_input(self) -> bool:
        """聚焦当前微信聊天输入区。"""
        hwnd = self._wx_hwnd()
        if hwnd <= 0:
            logger.error("focus_chat_input: hwnd无效")
            return False
        rect = self._hwnd_rect(hwnd)
        if not rect:
            logger.error("focus_chat_input: 无法获取微信窗口区域")
            return False
        if not self._ensure_wechat_foreground():
            logger.error("focus_chat_input: 微信窗口未处于前台")
            return False

        left, top, right, bottom = rect
        width = max(1, right - left)
        height = max(1, bottom - top)
        # 微信输入框通常位于右侧聊天区底部，避开左侧会话列表和顶部工具栏。
        x = left + int(width * 0.66)
        y = bottom - int(height * 0.08)
        pyautogui.click(x, y)
        time.sleep(0.15)
        return True

    def _wx_hwnd(self) -> int:
        """获取微信窗口句柄"""
        if not self.wx_window:
            return 0
        try:
            return _timeout_call(
                lambda: int(getattr(self.wx_window, "NativeWindowHandle", 0) or 0),
                default=0,
                timeout_ms=2000,
            )
        except Exception as e:
            logger.debug(f"获取窗口句柄失败: {e}")
            return 0

    def _wx_pid(self) -> int:
        """获取微信进程 ID"""
        if not self.wx_window:
            return 0
        try:
            return _timeout_call(
                lambda: int(getattr(self.wx_window, "ProcessId", 0) or 0),
                default=0,
                timeout_ms=2000,
            )
        except Exception as e:
            logger.debug(f"获取进程 ID 失败: {e}")
            return 0

    def _hwnd_rect(self, hwnd: int):
        """获取窗口矩形"""
        if hwnd <= 0:
            return None
        rect = wintypes.RECT()
        ok = _timeout_call(
            lambda: bool(user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))),
            default=False,
            timeout_ms=2000,
        )
        if not ok:
            return None
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    def _screen_rect(self):
        """获取屏幕尺寸"""
        sw = int(user32.GetSystemMetrics(0) or 0)
        sh = int(user32.GetSystemMetrics(1) or 0)
        if sw <= 0 or sh <= 0:
            sw, sh = 1920, 1080
        return 0, 0, sw, sh

    def _monitor_rect_for_window(self, hwnd: int):
        """获取窗口所在显示器矩形"""
        hwnd = ctypes.c_void_p(hwnd)
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return self._screen_rect()
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(mi)):
            return self._screen_rect()
        r = mi.rcMonitor
        return int(r.left), int(r.top), int(r.right), int(r.bottom)

    def _log_window_info(self, hwnd: int, context: str):
        """记录窗口详细信息"""
        if hwnd <= 0:
            logger.debug(f"[窗口] {context}: hwnd=0 (无效)")
            return
        title_len = user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
        title = ctypes.create_unicode_buffer(title_len + 1)
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, title_len + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), class_buf, 256)
        logger.debug(
            f"[窗口] {context}: hwnd={hwnd}, title='{title.value}', class='{class_buf.value}'"
        )

    def _ensure_wechat_foreground(self, timeout_s: float = 1.0) -> bool:
        """激活微信窗口到前台"""
        hwnd = self._wx_hwnd()
        if hwnd <= 0:
            logger.warning("_ensure_wechat_foreground: hwnd无效")
            return False

        fg = int(user32.GetForegroundWindow() or 0)
        if fg == hwnd:
            return True

        time.sleep(0.1)

        try:
            pyautogui.hotkey("ctrl", "alt", "w")
            time.sleep(0.4)
        except Exception as e:
            logger.warning(f"[激活] Ctrl+Alt+W 失败: {e}")

        fg_after = int(user32.GetForegroundWindow() or 0)
        if fg_after == hwnd:
            return True

        try:
            if _switch_to_this_window:
                _switch_to_this_window(ctypes.c_void_p(hwnd), True)
                time.sleep(0.2)
        except Exception:
            pass

        try:
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            time.sleep(0.2)
        except Exception:
            pass

        return True

    def switch_chat(self, chat_name: str, force: bool = True) -> bool:
        """切换到指定聊天会话"""
        import pyperclip

        if not chat_name:
            return True
        if self._looks_mojibake(chat_name):
            logger.error(f"[switch_chat] 会话名疑似乱码，拒绝切换: {chat_name!r}")
            return False
        if not force and chat_name == self.current_chat:
            logger.debug(f"[switch_chat] 已在目标聊天 {chat_name}，跳过切换")
            return True
        if not self.wx_window:
            logger.error("switch_chat: wx_window 未初始化")
            return False

        logger.debug(f"[switch_chat] 开始切换到: {chat_name}")

        try:
            if not self._ensure_wechat_foreground():
                logger.error("[switch_chat] 切换失败：微信窗口未处于前台")
                return False

            send_hotkey("ctrl", "f")
            time.sleep(0.5)

            pyperclip.copy("")
            time.sleep(0.05)
            pyperclip.copy(chat_name)
            time.sleep(0.15)

            send_hotkey("ctrl", "v")
            time.sleep(0.3)
            send_hotkey("enter")
            time.sleep(0.8)
            send_hotkey("esc")
            time.sleep(0.2)
            if not self.focus_chat_input():
                logger.error(f"[switch_chat] 切换后无法聚焦输入框: {chat_name}")
                return False

            self.current_chat = chat_name
            logger.debug(f"[switch_chat] 切换成功: current_chat={chat_name}")
            return True
        except Exception as e:
            logger.error(f"[switch_chat] 切换异常：{e}")
            return False

    def _rect_visible_ratio(self, rect):
        """计算窗口在屏幕上的可见比例"""
        if not rect:
            return 0.0
        left, top, right, bottom = rect
        sw = int(user32.GetSystemMetrics(0) or 1920)
        sh = int(user32.GetSystemMetrics(1) or 1080)
        vis_l = max(0, left)
        vis_t = max(0, top)
        vis_r = min(right, sw)
        vis_b = min(bottom, sh)
        vis_w = max(0, vis_r - vis_l)
        vis_h = max(0, vis_b - vis_t)
        win_w = max(1, right - left)
        win_h = max(1, bottom - top)
        return (vis_w * vis_h) / (win_w * win_h)

    def _best_wechat_hwnd(self, preferred_pid: int = 0) -> int:
        """查找最佳微信窗口句柄"""
        candidates = []
        browser_classes = {
            "chrome_widgetwin_1",
            "mozillaui_class",
            "safari",
            "chromium",
            "opera",
            "browser",
            "awindow",
            "ffwindow",
            "navigator",
        }
        browser_procs = {
            "chrome",
            "firefox",
            "msedge",
            "opera",
            "brave",
            "vivaldi",
            "360se",
            "liebao",
            "sogou",
            "maxthon",
        }

        def _cb(hwnd, _lparam):
            try:
                h = int(hwnd)
                if h <= 0:
                    return True
                if not bool(user32.IsWindowVisible(ctypes.c_void_p(h))):
                    return True
                if bool(user32.IsIconic(ctypes.c_void_p(h))):
                    return True
                rect = self._hwnd_rect(h)
                if not rect:
                    return True
                left, top, right, bottom = rect
                w = max(0, right - left)
                hgt = max(0, bottom - top)
                area = w * hgt
                if area < 120000:
                    return True
                pid = ctypes.c_ulong(0)
                user32.GetWindowThreadProcessId(ctypes.c_void_p(h), ctypes.byref(pid))
                pid_i = int(pid.value or 0)
                title_len = int(user32.GetWindowTextLengthW(ctypes.c_void_p(h)) or 0)
                title_buf = ctypes.create_unicode_buffer(max(2, title_len + 2))
                user32.GetWindowTextW(ctypes.c_void_p(h), title_buf, len(title_buf))
                title = str(title_buf.value or "")
                cls_buf = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(ctypes.c_void_p(h), cls_buf, len(cls_buf))
                cls = str(cls_buf.value or "").lower()
                title_lower = title.lower()

                if cls in browser_classes:
                    return True

                try:
                    proc = psutil.Process(pid_i)
                    proc_name = proc.name().lower()
                    if any(bp in proc_name for bp in browser_procs):
                        return True
                except Exception:
                    pass

                low = f"{title_lower}|{cls}".lower()
                if (
                    "wechat" not in low
                    and "weixin" not in low
                    and "微信" not in low
                    and "mainwnd" not in low
                    and "qt5" not in low
                    and "forpc" not in low
                ):
                    return True
                vis = self._rect_visible_ratio(rect)
                score = float(area)
                if "qt5" in cls or "forpc" in title_lower:
                    score += 800000.0
                if "mainwnd" in low:
                    score += 350000.0
                score += vis * 250000.0
                if pid_i == preferred_pid or preferred_pid == 0:
                    wechat_names = {"weixin.exe", "wechat.exe"}
                    try:
                        proc = psutil.Process(pid_i)
                        if proc.name().lower() in wechat_names:
                            score += 500000.0
                    except Exception:
                        pass
                if vis < 0.18:
                    score -= 420000.0
                candidates.append((score, int(h)))
            except Exception as e:
                logger.debug(f"枚举窗口时出错: {e}")
            return True

        try:
            user32.EnumWindows(
                ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_cb), 0
            )
        except Exception as e:
            logger.warning(f"EnumWindows 失败: {e}")

        logger.info(f"[_best_wechat_hwnd] 找到 {len(candidates)} 个候选窗口")
        if not candidates:
            return 0
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _normalize_wechat_window_rect(self):
        """规范化微信窗口位置"""
        hwnd = self._wx_hwnd()
        if hwnd <= 0:
            return
        rect = self._hwnd_rect(hwnd)
        if not rect:
            return
        left, top, right, bottom = rect
        w = right - left
        hgt = bottom - top
        sw = int(user32.GetSystemMetrics(0) or 1920)
        sh = int(user32.GetSystemMetrics(1) or 1080)
        if w > sw or hgt > sh:
            try:
                user32.MoveWindow(ctypes.c_void_p(hwnd), 0, 0, min(w, sw), min(hgt, sh), True)
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"MoveWindow 失败: {e}")

    def connect_wechat(self) -> bool:
        """连接微信窗口（完整版）"""
        logger.info("查找微信窗口...")

        best_hwnd = self._best_wechat_hwnd(0)
        logger.info(f"_best_wechat_hwnd 返回: {best_hwnd}")

        if best_hwnd > 0:
            try:
                self.wx_window = auto.ControlFromHandle(best_hwnd)
                logger.info(f"ControlFromHandle 成功，窗口Exists: {self.wx_window.Exists()}")
            except Exception as e:
                logger.warning(f"ControlFromHandle 失败: {e}")
                self.wx_window = auto.WindowControl(Name="微信")
        else:
            self.wx_window = auto.WindowControl(Name="微信")
            if not (self.wx_window and self.wx_window.Exists()):
                self.wx_window = auto.WindowControl(Name="Weixin")
                if not (self.wx_window and self.wx_window.Exists()):
                    logger.error("未找到微信窗口，请确保微信已打开")
                    return False

        self._normalize_wechat_window_rect()

        hwnd = self._wx_hwnd()
        rect = self._hwnd_rect(hwnd)
        logger.info(f"最终窗口句柄={hwnd} rect={rect}")
        return True
