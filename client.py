#!/usr/bin/env python3
"""kokoro-speak — thin stdlib-only client for ``kokoro-speakd``.

Usage::

    echo "hello" | kokoro-speak           # speak stdin (Stop hook path)
    kokoro-speak interrupt                # stop ongoing playback
    kokoro-speak ping                     # check if the daemon is alive
    kokoro-speak status                   # alias for ping

Environment::

    KOKORO_VOICE          voice id (default: af_sky)
    KOKORO_LANG           lang code (default: a)
    KOKORO_MAX            max chars to send (default: 5000)
    KOKORO_SPEAKD_SOCKET  override daemon socket path

Exit codes: always 0 from the ``speak`` path so Claude Code hooks never
fail loudly on TTS problems. ``ping`` returns 1 if the daemon is down.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

# Importable either as a package (when the flake installs us into a module
# layout) or as a loose script next to markdown.py (during `python3 client.py`).
try:  # pragma: no cover
    from .markdown import extract_summary, strip_markdown
except ImportError:
    _here = Path(__file__).resolve().parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    from markdown import extract_summary, strip_markdown  # type: ignore

DEFAULT_SOCKET = Path.home() / ".cache" / "claude-code-tts" / "kokoro-speakd.sock"
RECV_BUF = 65536
TIMEOUT = 5.0


def send(req: dict, sock_path: Path) -> dict:
    if not sock_path.exists():
        return {"status": "error", "error": f"daemon socket missing: {sock_path}"}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect(str(sock_path))
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        data = s.recv(RECV_BUF)
    except OSError as exc:
        return {"status": "error", "error": str(exc)}
    else:
        try:
            return json.loads(data.decode("utf-8").strip() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {"status": "error", "error": f"bad reply: {exc}"}
    finally:
        try:  # noqa: SIM105 — NameError catch is intentional (s may be unbound)
            s.close()  # type: ignore[name-defined]
        except (OSError, NameError):
            pass


def cmd_interrupt(sock_path: Path) -> int:
    resp = send({"action": "interrupt"}, sock_path)
    if resp.get("status") != "ok":
        sys.stderr.write(f"kokoro-speak: interrupt: {resp}\n")
    return 0


def cmd_ping(sock_path: Path) -> int:
    resp = send({"action": "ping"}, sock_path)
    sys.stdout.write(json.dumps(resp) + "\n")
    return 0 if resp.get("status") == "pong" else 1


def cmd_speak(sock_path: Path) -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0

    summary = extract_summary(raw)
    text = strip_markdown(summary if summary else raw)
    if not text:
        return 0

    try:
        max_chars = int(os.environ.get("KOKORO_MAX", "5000"))
    except ValueError:
        max_chars = 5000
    text = text[:max_chars]

    req = {
        "action": "speak",
        "text": text,
        "voice": os.environ.get("KOKORO_VOICE", "af_sky"),
        "lang": os.environ.get("KOKORO_LANG", "a"),
    }
    resp = send(req, sock_path)
    if resp.get("status") not in ("queued", "ok", "empty", "loading"):
        sys.stderr.write(f"kokoro-speak: {resp}\n")
    elif resp.get("status") == "loading":
        sys.stderr.write("kokoro-speak: daemon still loading model\n")
    # Always 0 — TTS is best-effort; never fail the calling hook.
    return 0


def main() -> int:
    sock_path = Path(os.environ.get("KOKORO_SPEAKD_SOCKET", str(DEFAULT_SOCKET)))
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action in ("interrupt", "stop"):
            return cmd_interrupt(sock_path)
        if action in ("ping", "status"):
            return cmd_ping(sock_path)
        if action in ("-h", "--help", "help"):
            sys.stdout.write(__doc__ or "")
            return 0
        if action != "speak":
            sys.stderr.write(f"kokoro-speak: unknown action: {action}\n")
            return 2
    return cmd_speak(sock_path)


if __name__ == "__main__":
    sys.exit(main())
