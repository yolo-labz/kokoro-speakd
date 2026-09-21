"""Stdlib regression checks for real client output and committed audio evidence."""

import array
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DemoTest(unittest.TestCase):
    def test_client_output_matches_protocol(self):
        import os

        with tempfile.TemporaryDirectory() as temporary:
            sock = str(Path(temporary) / "demo.sock")
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(sock)
                server.listen()

                def respond():
                    for response in (
                        {"status": "pong", "ready": True},
                        {"status": "queued", "id": 1},
                        {"status": "ok"},
                    ):
                        with server.accept()[0] as connection:
                            connection.recv(65536)
                            connection.sendall((json.dumps(response) + "\n").encode())

                thread = threading.Thread(target=respond, daemon=True)
                thread.start()
                for action in ("ping", "speak", "interrupt"):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "client.py"), action],
                        input="Synthetic test text",
                        env=dict(os.environ, KOKORO_SPEAKD_SOCKET=sock),
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=True,
                    )
                    self.assertEqual(result.stderr, "")
                    if action == "ping":
                        self.assertEqual(json.loads(result.stdout), {"status": "pong", "ready": True})
                    else:
                        self.assertEqual(result.stdout, "")
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

    def test_recorded_audio_and_cast(self):
        import re

        assets = ROOT / "docs/assets/recording-2026-09-21"
        meta = json.loads((assets / "metadata.json").read_text())
        with wave.open(str(assets / "kokoro-demo.wav")) as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 24000))
            samples = array.array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        audible = [i / 24000 for i, sample in enumerate(samples) if abs(sample) > 200]
        self.assertTrue(audible, "recording must contain real sound")
        self.assertGreater(audible[-1] - audible[0], 2)
        self.assertLess(audible[-1] - audible[0], 5)
        self.assertLess(max(abs(s) for s in samples[-24000:]), 100, "last second must be quiet")
        self.assertAlmostEqual(audible[-1], meta["interrupt_command_seconds"], delta=1)
        log = (assets / "daemon.log").read_text()
        match = re.search(r"samples=(\d+)", log)
        assert match is not None
        source_samples = int(match[1])
        self.assertGreater(source_samples / 24000, 8, "source must outlast the interrupted playback")
        cast = [json.loads(line) for line in (assets / "kokoro-demo.cast").read_text().splitlines()]
        self.assertEqual(cast[0]["version"], 2)
        output = "".join(event[2] for event in cast[1:])
        self.assertIn('"ready": true', output)
        self.assertIn("$ kokoro-speak interrupt", output)
        self.assertNotIn("412", output)
        self.assertNotIn("458", output)


if __name__ == "__main__":
    unittest.main()
