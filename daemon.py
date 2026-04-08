#!/usr/bin/env python3
"""kokoro-speakd — persistent Kokoro TTS daemon.

Loads the Kokoro PyTorch model exactly once and serves synthesis requests
over a Unix domain socket. A single shared daemon replaces the "reload the
model for every response" behaviour of naive hook-based integrations, which
is the only practical way to run Kokoro alongside dozens of concurrent
Claude Code instances without melting the machine.

Design highlights:

* **Preemption over queueing.** New speech requests always cancel the
  previous one (killing the in-flight afplay process and flagging the
  worker thread to bail on the next chunk). Rationale: with many parallel
  clients the user is realistically only watching the *latest* response;
  queueing stale speech would just create a drift nobody listens to.
* **Lazy per-language pipelines.** KPipeline is tied to a lang_code, so
  we cache one per lang on first use. Default English is loaded + warmed
  at startup; other languages spin up on demand.
* **Ready gate.** The socket binds immediately so launchd never marks the
  agent as failing, but speak requests return ``{"status":"loading"}``
  until the background warmup thread finishes. First response after a
  cold login is ~30s; subsequent ones across every client are <500ms.
* **Lean client protocol.** Line-delimited JSON, one request per
  connection, no long-lived streams. Clients disconnect as soon as the
  request is queued — audio plays in the daemon's own process tree.

Protocol (one JSON object per connection, terminated by newline)::

    Request     Response
    -------     --------
    {"action":"speak","text":"hello","voice":"af_sky","lang":"a"}
        -> {"status":"queued","id":42}
        -> {"status":"loading"}           # model still warming
        -> {"status":"empty"}             # text was whitespace
    {"action":"interrupt"}
        -> {"status":"ok"}
    {"action":"ping"}
        -> {"status":"pong","ready":true}

Environment overrides:

* ``KOKORO_SPEAKD_SOCKET``  path to the Unix socket file
* ``KOKORO_DEFAULT_VOICE``  voice used when a request omits ``voice``
* ``KOKORO_DEFAULT_LANG``   lang_code used when a request omits ``lang``
* ``KOKORO_SPEAKD_LOG``     override log file path (default cache dir)
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path(
    os.environ.get(
        "KOKORO_SPEAKD_CACHE",
        str(Path.home() / ".cache" / "claude-code-tts"),
    )
)
DEFAULT_SOCKET = CACHE_DIR / "kokoro-speakd.sock"
DEFAULT_LOG = CACHE_DIR / "kokoro-speakd.log"
SAMPLE_RATE = 24000
MAX_REQUEST_BYTES = 2 * 1024 * 1024  # 2 MiB is already absurd for a TTS prompt


def log(msg: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{stamp}] {msg}\n"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = Path(os.environ.get("KOKORO_SPEAKD_LOG", str(DEFAULT_LOG)))
        with log_path.open("a") as f:
            f.write(line)
    except OSError:
        pass
    # launchd redirects stderr to its own log file — always mirror there too.
    sys.stderr.write(line)
    sys.stderr.flush()


class Speaker:
    """Owns the Kokoro pipelines and the single active playback process."""

    def __init__(self) -> None:
        self.pipelines: dict[str, object] = {}
        self.pipelines_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.current_req_id = 0
        self.current_player: "subprocess.Popen | None" = None
        self.ready = threading.Event()
        self._KPipeline = None
        self._np = None
        self._sf = None

    # ------------------------------------------------------------------
    # Warmup

    def load(self) -> None:
        log("loading kokoro runtime...")
        try:
            from kokoro import KPipeline  # type: ignore
            import numpy as np  # type: ignore
            import soundfile as sf  # type: ignore
        except Exception as exc:
            log(f"FATAL import error: {exc!r}")
            raise

        self._KPipeline = KPipeline
        self._np = np
        self._sf = sf

        default_lang = os.environ.get("KOKORO_DEFAULT_LANG", "a")
        default_voice = os.environ.get("KOKORO_DEFAULT_VOICE", "af_sky")
        try:
            pipeline = KPipeline(lang_code=default_lang)
            self.pipelines[default_lang] = pipeline
        except Exception as exc:
            log(f"FATAL pipeline init error: {exc!r}")
            raise

        # Warmup synth primes torch weights, JIT, and spaCy en_core_web_sm.
        try:
            for _ in pipeline("ready", voice=default_voice):
                break
            log("warmup synth complete")
        except Exception as exc:
            log(f"warmup synth error (continuing anyway): {exc!r}")

        self.ready.set()
        log(f"daemon ready (default lang={default_lang}, voice={default_voice})")

    def get_pipeline(self, lang: str):
        with self.pipelines_lock:
            if lang not in self.pipelines:
                log(f"lazy loading pipeline lang={lang}")
                if self._KPipeline is None:
                    raise RuntimeError("model not loaded yet")
                self.pipelines[lang] = self._KPipeline(lang_code=lang)
            return self.pipelines[lang]

    # ------------------------------------------------------------------
    # Preemption + speech

    def preempt(self) -> int:
        """Bump the request generation and kill any active playback.
        Returns the new request id the caller should use for its worker."""
        with self.state_lock:
            self.current_req_id += 1
            rid = self.current_req_id
            if self.current_player is not None:
                try:
                    self.current_player.kill()
                except OSError:
                    pass
                self.current_player = None
        return rid

    def speak(self, text: str, voice: str, lang: str) -> int:
        rid = self.preempt()
        threading.Thread(
            target=self._worker,
            name=f"speak-{rid}",
            args=(rid, text, voice, lang),
            daemon=True,
        ).start()
        return rid

    def _is_current(self, rid: int) -> bool:
        with self.state_lock:
            return rid == self.current_req_id

    def _worker(self, rid: int, text: str, voice: str, lang: str) -> None:
        try:
            pipeline = self.get_pipeline(lang)
        except Exception as exc:
            log(f"pipeline load error rid={rid}: {exc!r}")
            return

        chunks = []
        try:
            for result in pipeline(text, voice=voice):
                if not self._is_current(rid):
                    log(f"preempted mid-synth rid={rid}")
                    return
                audio = getattr(result, "audio", None)
                if audio is None:
                    continue
                if hasattr(audio, "cpu"):
                    audio = audio.cpu().numpy()
                chunks.append(audio)
        except Exception as exc:
            log(f"synth error rid={rid}: {exc!r}")
            return

        if not chunks:
            log(f"no audio produced rid={rid}")
            return

        audio = self._np.concatenate(chunks)

        # Keep the wav inside our cache dir so lingering files after a crash
        # are easy to find and clean up.
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav",
            prefix=f"kokoro-{rid}-",
            delete=False,
            dir=str(CACHE_DIR),
        )
        tmp.close()
        self._sf.write(tmp.name, audio, SAMPLE_RATE)

        with self.state_lock:
            if rid != self.current_req_id:
                log(f"preempted before playback rid={rid}")
                _unlink(tmp.name)
                return
            player = _pick_player(tmp.name)
            if player is None:
                log("no audio player on PATH (afplay/aplay/paplay)")
                _unlink(tmp.name)
                return
            try:
                proc = subprocess.Popen(
                    player,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                log(f"player spawn error rid={rid}: {exc!r}")
                _unlink(tmp.name)
                return
            self.current_player = proc
            log(
                f"playing rid={rid} pid={proc.pid} samples={len(audio)} wav={tmp.name}"
            )

        try:
            proc.wait()
        except Exception:  # pragma: no cover
            pass

        with self.state_lock:
            if self.current_player is proc:
                self.current_player = None

        _unlink(tmp.name)
        log(f"finished rid={rid}")


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _pick_player(path: str) -> "list[str] | None":
    rate = os.environ.get("KOKORO_PLAYBACK_RATE", "1")
    for name, extras in (
        ("afplay", ["-r", rate]),
        ("aplay", ["-q"]),
        ("paplay", []),
    ):
        if shutil.which(name):
            return [name, *extras, path]
    return None


# ----------------------------------------------------------------------
# Socket server


def serve(sock_path: Path, speaker: Speaker) -> None:
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        sock_path.unlink()
    except FileNotFoundError:
        pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    os.chmod(str(sock_path), 0o600)
    srv.listen(32)
    log(f"listening on {sock_path}")

    while True:
        try:
            conn, _ = srv.accept()
        except KeyboardInterrupt:
            raise
        except OSError as exc:
            log(f"accept error: {exc!r}")
            continue
        threading.Thread(
            target=handle_connection,
            args=(conn, speaker),
            daemon=True,
        ).start()


def handle_connection(conn: socket.socket, speaker: Speaker) -> None:
    try:
        conn.settimeout(10)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_REQUEST_BYTES:
                respond(conn, {"status": "error", "error": "request too large"})
                return
        line, _, _ = buf.partition(b"\n")
        if not line:
            return
        try:
            req = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            respond(conn, {"status": "error", "error": f"bad json: {exc}"})
            return

        action = req.get("action", "speak")

        if action == "ping":
            respond(
                conn,
                {"status": "pong", "ready": speaker.ready.is_set()},
            )
            return

        if action == "interrupt":
            speaker.preempt()
            respond(conn, {"status": "ok"})
            return

        if action == "speak":
            if not speaker.ready.is_set():
                respond(conn, {"status": "loading"})
                return
            text = (req.get("text") or "").strip()
            if not text:
                respond(conn, {"status": "empty"})
                return
            voice = (
                req.get("voice")
                or os.environ.get("KOKORO_DEFAULT_VOICE", "af_sky")
            )
            lang = (
                req.get("lang")
                or os.environ.get("KOKORO_DEFAULT_LANG", "a")
            )
            rid = speaker.speak(text, voice, lang)
            respond(conn, {"status": "queued", "id": rid})
            return

        respond(
            conn,
            {"status": "error", "error": f"unknown action: {action}"},
        )
    except Exception as exc:
        log(f"handler error: {exc!r}")
        try:
            respond(conn, {"status": "error", "error": str(exc)})
        except OSError:
            pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def respond(conn: socket.socket, payload: dict) -> None:
    conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))


# ----------------------------------------------------------------------
# Entry point


def main() -> int:
    # Ignore SIGPIPE so a client disconnecting mid-response doesn't kill us.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    sock_path = Path(
        os.environ.get("KOKORO_SPEAKD_SOCKET", str(DEFAULT_SOCKET))
    )

    speaker = Speaker()
    # Background model load so the socket binds immediately and launchd is
    # happy. Speak requests return {"status":"loading"} until ready.
    threading.Thread(target=speaker.load, name="load", daemon=True).start()

    try:
        serve(sock_path, speaker)
    except KeyboardInterrupt:
        log("shutdown requested")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
