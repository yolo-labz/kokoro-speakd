# Truthful media slice

## Spec
Replace unsupported terminal/latency claims with real client output and audio from
an isolated daemon; exercise interrupt during audible speech. Never touch the live
socket, physical audio sink, accounts, browser profiles or hardware fan controls.
Correct release wording against public PyPI metadata. Secondary repositories need
their own feature branches and explicit capture/provenance limitations.

## Plan
Reuse the completed Nix daemonEnv fetch and existing daemon/client unchanged.
Capture PulseAudio null-sink monitor audio (no physical playback); record actual
client stdout/stderr in asciinema v2 format. Fail capture unless speech is audible
before interrupt and silence follows. Preserve source, metadata, tests and audio.
Do not report queue acknowledgement as speech-onset latency.

## Tasks
- [x] Execute isolated TTS + interrupt recording and validate audio.
- [x] Remove fabricated/unsupported output and latency from README/cast.
- [x] Check PyPI metadata and document runtime packaging limitation if present.
- [ ] Capture isolated zellij or record concrete runtime blocker.
- [x] Inspect/correct Chrome pair and fand media claims in separate worktrees.
- [x] Run tests and write docs/swarm-2026-09-21.md with all five dispositions.
- [ ] Coordinator: full GLM independent gate (OpenAI implementation), PR/merge.
