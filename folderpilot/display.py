"""Windows DPI setup must run before Tk creates any window."""
import ctypes
import sys


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(ctypes.c_void_p(-4)) or ctypes.get_last_error() == 5:
            return  # A packaged manifest may already have set the process mode.
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def window_dpi(window) -> int:
    if sys.platform == "win32":
        try:
            getter = ctypes.windll.user32.GetDpiForWindow
            getter.argtypes = [ctypes.c_void_p]
            getter.restype = ctypes.c_uint
            dpi = getter(ctypes.c_void_p(window.winfo_id()))
            if dpi:
                return dpi
        except (AttributeError, OSError):
            pass
    return round(window.winfo_fpixels("1i"))
