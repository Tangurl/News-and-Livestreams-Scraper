# sitecustomize.py - Global compatibility patches for Selenium Headless Chrome on Windows
import sys

# Ensure UTF-8 console output
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Automatically inject stability and GPU-disable flags into Selenium Chrome Options
try:
    from selenium.webdriver.chrome.options import Options
    _orig_init = Options.__init__
    def _patched_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        self.add_argument("--disable-gpu")
        self.add_argument("--disable-software-rasterizer")
    Options.__init__ = _patched_init
except Exception:
    pass
