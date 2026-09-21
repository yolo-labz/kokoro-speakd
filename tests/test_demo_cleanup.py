"""Owned-process cleanup regressions; no real audio server or child is touched."""

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "record_demo", Path(__file__).resolve().parents[1] / "scripts/record-demo.py"
)
assert spec is not None and spec.loader is not None
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


class CleanupTest(unittest.TestCase):
    def test_timeout_escalates_and_unloads(self):
        capture, daemon = Mock(), Mock()
        capture.wait.side_effect = [subprocess.TimeoutExpired("owned", 10), None]
        with patch.object(recorder.subprocess, "run") as run:
            recorder.cleanup(capture, daemon, "owned-module", {})
        capture.kill.assert_called_once_with()
        daemon.terminate.assert_called_once_with()
        self.assertEqual(run.call_args.args[0], ["pactl", "unload-module", "owned-module"])

    def test_failed_reap_still_cleans_other_resources(self):
        capture, daemon = Mock(), Mock()
        capture.wait.side_effect = [subprocess.TimeoutExpired("owned", 10), OSError("reap failed")]
        with patch.object(recorder.subprocess, "run") as run, self.assertRaises(OSError):
            recorder.cleanup(capture, daemon, "owned-module", {})
        daemon.terminate.assert_called_once_with()
        self.assertEqual(run.call_args.args[0], ["pactl", "unload-module", "owned-module"])

    def test_interrupt_timeout_still_terminates_daemon(self):
        daemon = Mock()
        with (
            patch.object(
                recorder.subprocess, "run", side_effect=[subprocess.TimeoutExpired("interrupt", 5), None]
            ) as run,
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            recorder.cleanup(None, daemon, "owned-module", {})
        daemon.terminate.assert_called_once_with()
        self.assertEqual(run.call_args.args[0], ["pactl", "unload-module", "owned-module"])


if __name__ == "__main__":
    unittest.main()
