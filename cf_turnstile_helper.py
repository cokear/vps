# -*- coding: utf-8 -*-
"""Cloudflare Turnstile helper for SeleniumBase scripts."""

import os
import subprocess
import time


_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden' || el.classList.contains('modal-content') || el.classList.contains('modal-dialog')) {
            el.style.overflow = 'visible';
            el.style.zIndex = '999999';
        }
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1'; f.style.zIndex = '999999';
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
(function(){
    return document.querySelector('input[name="cf-turnstile-response"]') !== null;
})()
"""

_SOLVED_JS = """
(function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
})()
"""

_COORDS_JS = """
(function(){
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenges')) {
            var r = iframes[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
        }
    }
    var inp = document.querySelector('input[name="cf-turnstile-response"]');
    if (inp) {
        var p = inp.parentElement;
        for (var j = 0; j < 5; j++) {
            if (!p) break;
            var r = p.getBoundingClientRect();
            if (r.width > 100 && r.height > 30)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
            p = p.parentElement;
        }
    }
    return null;
})()
"""

_WININFO_JS = """
(function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""


def is_turnstile_present(sb) -> bool:
    try:
        return bool(sb.execute_script(_EXISTS_JS))
    except Exception:
        return False


def is_turnstile_solved(sb) -> bool:
    try:
        return bool(sb.execute_script(_SOLVED_JS))
    except Exception:
        return False


def get_window_metrics_js() -> str:
    return _WININFO_JS


def click_screen_point(x: int, y: int):
    _xdotool_click(x, y)


def detect_cloudflare_challenge(sb) -> bool:
    """Best-effort detection of Cloudflare challenge pages/widgets."""
    try:
        page_source = str(sb.get_page_source() or "").lower()
    except Exception:
        page_source = ""
    try:
        title = str(sb.get_title() or "")
    except Exception:
        title = ""

    indicators = (
        "turnstile",
        "challenges.cloudflare",
        "just a moment",
        "verify you are human",
    )
    if any(item in page_source for item in indicators):
        return True
    return "just a moment" in title.lower()


def handle_cloudflare_if_present(sb) -> bool:
    """
    One-liner helper:
    auto-detect CF challenge and solve Turnstile when present.
    Returns True only when a challenge was detected and solved.
    """
    if not detect_cloudflare_challenge(sb):
        return False
    if not is_turnstile_present(sb):
        return False
    return handle_turnstile(sb)


def handle_turnstile(sb) -> bool:
    print("[cf] handling Cloudflare Turnstile...")
    time.sleep(2)

    if is_turnstile_solved(sb):
        print("[cf] already solved")
        return True

    for _ in range(3):
        try:
            sb.execute_script(_EXPAND_JS)
        except Exception:
            pass
        time.sleep(0.5)

    for attempt in range(6):
        if is_turnstile_solved(sb):
            print(f"[cf] solved (attempt {attempt + 1})")
            return True

        try:
            sb.execute_script(_EXPAND_JS)
        except Exception:
            pass
        time.sleep(0.3)

        _click_turnstile(sb)

        for _ in range(8):
            time.sleep(0.5)
            if is_turnstile_solved(sb):
                print(f"[cf] solved (attempt {attempt + 1})")
                return True

        print(f"[cf] attempt {attempt + 1} failed, retrying...")

    print("[cf] failed after 6 attempts")
    return False


def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--class", cls],
                capture_output=True,
                text=True,
                timeout=3,
            )
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wids[0]],
                    timeout=3,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.2)
                return
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdotool", "getactivewindow", "windowactivate"],
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _xdotool_click(x: int, y: int):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")


def _click_turnstile(sb):
    try:
        coords = sb.execute_script(_COORDS_JS)
    except Exception as e:
        print(f"[cf] failed to get turnstile coords: {e}")
        return

    if not coords:
        print("[cf] unable to locate turnstile coords")
        return

    try:
        wi = sb.execute_script(_WININFO_JS)
    except Exception:
        wi = {"sx": 0, "sy": 0, "oh": 800, "ih": 768}

    bar = wi["oh"] - wi["ih"]
    ax = coords["cx"] + wi["sx"]
    ay = coords["cy"] + wi["sy"] + bar
    _xdotool_click(ax, ay)
