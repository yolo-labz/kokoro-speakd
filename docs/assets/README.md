# Actual Kokoro recording

Recorded 21/09/2026 on x86_64 Linux, source base `94cb7d2`. The existing Nix
`daemonEnv` build completed before recovery and was reused, not restarted.
Daemon/client source is unchanged. Generated speech uses `af_sky`, English,
Kokoro-82M PyTorch, a synthetic script and a private PulseAudio null sink.
No microphone, physical speaker, live speech socket, account data or music.

- [Short audiovisual excerpt](recording-2026-09-21/kokoro-demo.mp4): 960×240,
  waveform of actual captured playback, original speed, AAC mono audio.
  Only the initial synthesis wait was removed; `clip-edit.json` records the cut.
- [Unedited audio](recording-2026-09-21/kokoro-demo.wav): PCM16, 24 kHz mono.
- [Full synthesized source](recording-2026-09-21/full-utterance.wav): 21.3 s;
  compare with the roughly four seconds played before interrupt.
- [Actual client output](kokoro-demo.cast): asciinema v2, 100×24 cells.
  Prompt labels are added by the harness; stdout/stderr is actual subprocess output.
  `ping` prints JSON; successful speak/interrupt print nothing.

The cast and monitor recorder start independently; this is not a sample-synced
onset-latency benchmark. There is no claim that queue acknowledgement means audio
has started. See `../evidence/audio-ffprobe.json`, `video-ffprobe.json`, model hashes
and each recording's `metadata.json`. The exact executed recorder is preserved as
`recorder-source.py.txt`; the current script adds a type-narrowing assertion only.

## Reproduce

```bash
nix build .#daemonEnv --out-link /tmp/kokoro-demo-env
# pactl, parec, paplay must be on PATH and a PulseAudio-compatible server running.
OMP_NUM_THREADS=$(nproc) MKL_NUM_THREADS=$(nproc) \
  /tmp/kokoro-demo-env/bin/python scripts/record-demo.py /path/to/NEW-output-directory
uv run --no-project --with pytest python -m pytest -q
```

The script creates/removes only its own sink module, daemon, player and temporary
socket/cache. It refuses an existing output directory. `KOKORO_DEMO_HF_HOME` may
point at a separate demo model cache to reuse downloads; it never needs an account.
The recorder uses a 20 ms buffer: its default buffer previously dropped the quiet
tail on termination, and the committed audio test caught that failure.

## Provenance and rights

Text and recording scripts are original repository work under MIT. Speech was
generated locally, not copied from somebody else's recording. No soundtrack.
The [Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/README.md)
identifies Apache-2.0 weights (checked 21/09/2026); its upstream attribution section
credits Koniwa (CC BY 3.0) and SIWIS (CC BY 4.0) training contributions. Model files
are not redistributed here; revision and SHA-256 are in `../evidence/model-provenance.json`.
This is source/license provenance, not a legal warranty about generated output.
