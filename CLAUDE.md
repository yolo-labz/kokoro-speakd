# CLAUDE.md

Guidance for Claude Code sessions working on `kokoro-speakd`. Last updated 2026-04-11.

## What this is

Persistent Kokoro TTS daemon for Claude Code. The model is loaded once at daemon
startup and serves many client requests over a Unix socket, so the (~1s) model-warm
cost is paid once per login session instead of once per TTS invocation.

- **Repo:** https://github.com/yolo-labz/kokoro-speakd
- **Org:** `yolo-labz` (Pedro's org — note the **Z**, matching sibling plugins)
- **Working dir:** `~/Documents/Code/Nix/kokoro-speakd`
- **Sibling plugins:** `claude-mac-chrome`, `wa`, `claude-classroom-submit`
- **Current state:** pre-CI, pre-release. No `.github/`, no branch protection, no tag.

## Architecture in one paragraph

A `daemon.py` loads the Kokoro ONNX model once at launchd/systemd start, binds a
unix socket at `~/.cache/claude-code-tts/kokoro.sock`, and serves a tiny line-delimited
JSON protocol: `{"text": "...", "voice": "..."}` → synthesized WAV written to a
caller-specified path. `client.py` (installed as `kokoro-speak`) is the thin client
that Claude Code's Stop hook shells out to; `kokoro-speakd` is the daemon binary; a
`markdown.py` helper strips markdown to speakable plain text before synthesis. Pure
Python runtime, heavy ML deps: `torch`, `onnxruntime`, `kokoro` model weights.

## Layout

```
kokoro-speakd/
├── client.py        # kokoro-speak — thin client
├── daemon.py        # kokoro-speakd — persistent daemon
├── markdown.py      # Markdown → speakable text filter
├── flake.nix        # Nix package + launchd/systemd units
├── flake.lock
├── nix/             # Platform-specific Nix bits
├── LICENSE          # MIT
└── README.md
```

## Hard rules

1. **The daemon must own the model load.** Never instantiate the Kokoro model in
   `client.py`. The whole point of the daemon is to amortize the model warm cost.
2. **Unix socket only.** No HTTP, no TCP, no loopback port. The socket lives under
   `~/.cache/claude-code-tts/` with mode `0600`.
3. **Do not ship model weights through PyPI.** Declare `torch` and `onnxruntime` as
   `>=` pins in `[project.dependencies]`; consumers resolve platform-specific wheels
   from PyPI. Kokoro model weights ship as a **GitHub Release asset** (not PyPI) with
   an attestation over the file digest; the daemon downloads on first run with a
   hash-pinned URL.
4. **Never spawn torch in `client.py`.** Client must fail loud if the daemon is not
   reachable — no silent fallback that loads the model client-side.
5. **Launchd/systemd user agent, not root.** The daemon runs as the user; the
   flake's `home-manager` module wires this up.
6. **Stdin input only — never read from argv.** Prevents shell escaping mistakes
   with user text.

## Release engineering — shared standards

Release-engineering standards are shared across all self-coded yolo-labz Claude Code
plugins. The canonical source of truth lives in the NixOS config repo:

- **Research:** `~/NixOS/meta/yolo-labz-release-engineering-research.md`
- **Rollout plan:** `~/NixOS/meta/yolo-labz-release-engineering-plan.md`
- **Enforced rule:** `plugin-release-engineering` in `~/NixOS/modules/home/claude-code.nix`
  — loaded globally into every Claude Code session via home-manager.

**Current state:** greenfield. No CI, no `.github/`, no releases, no branch protection.

**Phase 2 rollout (see plan §6.2):**

1. Bootstrap `.github/` from scratch. Target files:
   `workflows/{ci,release,codeql,osv-scan,scorecard,sonar,reproducibility}.yml`,
   `dependabot.yml`, `scorecard-config.yml`, `actions-lock.md`.
2. `pyproject.toml` with **hatchling** build backend, `requires-python = ">=3.11"`,
   semver in both `pyproject.toml` and `.claude-plugin/plugin.json` — keep locked.
3. Declare `torch>=2.x` and `onnxruntime>=1.x` as install-requires. Add
   `[project.optional-dependencies]` for `gpu = ["onnxruntime-gpu"]`. **Do not vendor
   torch.** Do not use `cibuildwheel` — no C extensions to build.
4. `ci.yml`: `uvx ruff check && uvx ruff format --check && uvx pyright && uv run pytest`.
5. `release.yml`: `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) PYTHONHASHSEED=0 uv build`
   → `actions/attest-build-provenance@v2` → `pypa/gh-action-pypi-publish@release/v1`
   with PyPI Trusted Publishing (PEP 740 attestations auto-generated — do NOT add a
   separate `sigstore-python` step).
6. **Model weights workflow:** separate step that uploads kokoro weights as a release
   asset and runs `actions/attest-build-provenance` over the file digest. Daemon
   downloads on first run with hash-pinned URL; ignore-in-pypi via package-data.
7. `SECURITY.md`, `CODEOWNERS`, `CONTRIBUTING.md`. Enable Private Vulnerability
   Reporting.
8. Enable branch protection via Repository Ruleset from scratch (currently
   unprotected). Use `enforcement: disabled` → merge → `active` to bootstrap the
   required checks.
9. `.claude-plugin/plugin.json` with minimal manifest (see research §4.1 reference
   snippet). Ensure `version` wins over any future marketplace entry.
10. Tag `v0.1.0` as the first signed release. **Never re-tag.**

**ML-daemon-specific guidance:**

- `uv export --format=requirements-txt --generate-hashes > requirements.lock` as a
  release asset for downstream `pip install --require-hashes` consumers.
- CodeQL Python: `build-mode: none`, `paths-ignore: ['site-packages/**']` to scope
  analysis to the daemon code, not torch's transitive tree.
- SBOM via `syft` will be large due to torch transitives — archive as release asset,
  not in git. Expect OSV-Scanner to flag some transitive torch/onnxruntime CVEs; do
  not gate on zero findings. Triage-then-waive via VEX in the CycloneDX 1.7 doc.
- `ruff` replaces flake8/black/isort; `pyright` over mypy for the daemon's async code.
- Pin lint and type-check tool versions via `uv run --with` or `[tool.uv.dev-dependencies]`
  so CI is reproducible.
- Launchd/systemd unit files live under `nix/` and get installed via the flake. Keep
  them idempotent — activation must tolerate repeated runs.

**Invariants:**

1. Never ship torch wheels ourselves. Platform wheels come from PyPI.
2. Never re-tag a release.
3. Never commit model weights to git — they go to GitHub Release assets only.
4. The daemon socket path and mode (`~/.cache/claude-code-tts/kokoro.sock`, `0600`)
   are load-bearing for both security and the NixOS/nix-darwin activation scripts.
   Changing either requires coordinated updates in `flake.nix` and the home-manager
   integration at `~/NixOS/modules/home/claude-code.nix`.
5. Client must fail loud on daemon unavailability — never silently load the model
   client-side.
