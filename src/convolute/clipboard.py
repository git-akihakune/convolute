"""Copy text to the system clipboard with the platform's own tool."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping


class ClipboardError(Exception):
    """A diagnostic that is safe to print."""


def _find_tool(platform: str, environ: Mapping[str, str], which: Callable[[str], str | None]):
    if platform == "darwin":
        candidates = [(["pbcopy"], "utf-8")]
    elif platform == "win32":
        candidates = [(["clip"], "utf-16")]
    else:
        candidates = [(["wl-copy"], "utf-8")] if environ.get("WAYLAND_DISPLAY") else []
        candidates += [(["xclip", "-selection", "clipboard"], "utf-8"),
                       (["xsel", "--clipboard", "--input"], "utf-8"),
                       (["clip.exe"], "utf-16")]
    for command, encoding in candidates:
        path = which(command[0])
        if path:
            return [path, *command[1:]], encoding
    return None


def copy_text(text: str, *, platform: str = sys.platform, environ: Mapping[str, str] = os.environ,
              which: Callable[[str], str | None] = shutil.which, run=subprocess.run) -> None:
    """Send exactly `text` to the clipboard; raise ClipboardError if that is not possible."""
    found = _find_tool(platform, environ, which)
    if found is None:
        raise ClipboardError("no clipboard tool found (install pbcopy, wl-copy, xclip, or xsel)")
    command, encoding = found
    # clip.exe reads UTF-16 with a byte order mark; macOS pbcopy decodes by locale, so force UTF-8.
    data = ("﻿" + text).encode("utf-16-le") if encoding == "utf-16" else text.encode()
    env = {**environ, "LC_CTYPE": "UTF-8"} if platform == "darwin" else dict(environ)
    try:
        # DEVNULL, not pipes: a forked xclip keeps inherited pipes open and would stall the wait.
        completed = run(command, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=5, env=env, check=False)
    except (subprocess.TimeoutExpired, OSError):
        raise ClipboardError("the clipboard tool failed to run") from None
    if completed.returncode != 0:
        raise ClipboardError(f"the clipboard tool exited with status {completed.returncode}")
