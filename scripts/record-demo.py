#!/usr/bin/env python3
"""Record real Linux TTS/interrupt audio on a private null sink, never the speakers.

Run with the flake's daemonEnv Python and pactl/parec/paplay on PATH.
Output must be a NEW directory. No latency benchmark is implied by this capture.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (
    "This is real Kokoro speech, captured from an isolated audio sink. "
    "The next command will interrupt this sentence while it is still playing. "
    "This deliberately long synthetic example continues with more words so that "
    "the recording can demonstrate cancellation rather than natural completion. "
    "No personal messages, microphone input, or music are included."
)


def wait_for(check, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise TimeoutError("capture condition not reached")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for tool in ("pactl", "parec", "paplay"):
        if not shutil.which(tool):
            parser.error(f"missing {tool}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sink = f"kokoro_demo_{os.getpid()}"
    module = None
    daemon = recorder = None
    with tempfile.TemporaryDirectory(prefix="kokoro-demo-") as temporary:
        cache = Path(temporary)
        # Give only this daemon a player PATH; never select aplay's hardware default.
        player_bin = cache / "bin"
        player_bin.mkdir()
        paplay = shutil.which("paplay")
        assert paplay is not None  # Already checked above; also narrow the type.
        (player_bin / "paplay").symlink_to(paplay)
        env = dict(
            os.environ,
            PATH=str(player_bin),
            HF_HOME=os.environ.get("KOKORO_DEMO_HF_HOME", str(cache / "huggingface")),
            HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
            KOKORO_DEFAULT_VOICE="af_sky",
            KOKORO_VOICE="af_sky",
            KOKORO_DEFAULT_LANG="a",
            KOKORO_LANG="a",
            KOKORO_MAX="5000",
            KOKORO_SPEAKD_CACHE=str(cache),
            KOKORO_SPEAKD_SOCKET=str(cache / "demo.sock"),
            KOKORO_SPEAKD_LOG=str(output / "daemon.log"),
            PULSE_SINK=sink,
        )
        try:
            module = subprocess.check_output(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={sink}",
                    "rate=24000",
                    "channels=1",
                ],
                text=True,
            ).strip()
            with (output / "runtime.log").open("w") as log:
                daemon = subprocess.Popen([sys.executable, str(ROOT / "daemon.py")], env=env, stdout=log, stderr=log)

            def ready():
                if daemon.poll() is not None:
                    raise RuntimeError("daemon exited; see runtime.log")
                ping = subprocess.run(
                    [sys.executable, str(ROOT / "client.py"), "ping"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if (output / "daemon.log").exists() and "FATAL" in (output / "daemon.log").read_text():
                    raise RuntimeError("daemon warmup failed; see runtime.log")
                return ping.returncode == 0 and json.loads(ping.stdout).get("ready")

            wait_for(ready)
            with (output / "capture.raw").open("wb") as raw:
                recorder = subprocess.Popen(
                    [
                        "parec",
                        f"--device={sink}.monitor",
                        "--format=s16le",
                        "--rate=24000",
                        "--channels=1",
                        "--latency-msec=20",
                        "--process-time-msec=20",
                    ],
                    stdout=raw,
                    stderr=subprocess.PIPE,
                )
            start = time.monotonic()
            events = []

            def emit(text):
                events.append([round(time.monotonic() - start, 6), "o", text.replace("\n", "\r\n")])

            def client(action, text=None):
                emit(f"$ kokoro-speak {action}" + (" < synthetic-demo.txt" if text else "") + "\n")
                result = subprocess.run(
                    [sys.executable, str(ROOT / "client.py"), action],
                    input=text,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                emit(result.stdout + result.stderr)
                if action != "ping" and (result.stdout or result.stderr):
                    raise RuntimeError("expected silent successful client")

            emit("Isolated null-sink capture; synthetic text; real time; no latency benchmark.\n")
            client("ping")
            (output / "synthetic-demo.txt").write_text(TEXT + "\n")
            client("speak", TEXT)
            wait_for(lambda: "playing rid=" in (output / "daemon.log").read_text())
            playing = time.monotonic() - start
            wav_match = re.search(r"playing rid=.* wav=(.+)", (output / "daemon.log").read_text())
            if wav_match is None:
                raise RuntimeError("missing playback source")
            shutil.copyfile(wav_match[1], output / "full-utterance.wav")
            with wave.open(str(output / "full-utterance.wav")) as full:
                if full.getnframes() / full.getframerate() < 8:
                    raise RuntimeError("utterance too short to demonstrate interruption")
            time.sleep(4)
            interrupt = time.monotonic() - start
            client("interrupt")
            time.sleep(2)
            client("ping")
            elapsed = time.monotonic() - start
            recorder.terminate()
            recorder.wait(timeout=10)
            recorder = None
            raw_path = output / "capture.raw"
            with wave.open(str(output / "kokoro-demo.wav"), "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes(raw_path.read_bytes())
            raw_path.unlink()
            header = {
                "version": 2,
                "width": 100,
                "height": 24,
                "timestamp": int(time.time()),
                "title": "Real kokoro-speak client; paired null-sink audio",
                "env": {"TERM": "xterm-256color"},
            }
            (output / "kokoro-demo.cast").write_text("\n".join(json.dumps(x) for x in [header, *events]) + "\n")
            metadata = {
                "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "recorder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "python": sys.version,
                "python_executable": sys.executable,
                "capture": "PulseAudio null-sink monitor; no physical speaker or microphone",
                "voice": env.get("KOKORO_DEFAULT_VOICE", "af_sky"),
                "sample_rate": 24000,
                "channels": 1,
                "playback_speed": 1,
                "playing_log_observed_seconds": playing,
                "interrupt_command_seconds": interrupt,
                "wall_duration_seconds": elapsed,
                "music": None,
                "timing_note": "Cast and audio start independently; not sample-synchronised. No onset latency claim.",
            }
            (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
            print(json.dumps(metadata, indent=2))
        finally:
            if recorder is not None:
                recorder.terminate()
                recorder.wait(timeout=10)
            if daemon is not None:
                # Interrupt only OUR socket before terminating OUR daemon.
                subprocess.run(
                    [sys.executable, str(ROOT / "client.py"), "interrupt"], env=env, capture_output=True, check=False
                )
                daemon.terminate()
                daemon.wait(timeout=10)
            if module is not None:
                subprocess.run(["pactl", "unload-module", module], check=True)


if __name__ == "__main__":
    main()
