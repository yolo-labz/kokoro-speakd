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

## Release engineering (yolo-labz standards) — repo-scoped canon

<!-- Moved here from the global Claude rules layer (NixOS spec 887 FR-012): policy is repo-scoped, not fleet-global. -->

Release-engineering standards for every self-coded Claude Code plugin in the
yolo-labz GitHub org (claude-mac-chrome, wa, kokoro-speakd, claude-classroom-submit,
homebrew-tap). Derived from ~/NixOS/meta/yolo-labz-release-engineering-research.md —
read it in full before any release-engineering work on these repos. Do NOT apply
these rules to unrelated projects.

## Supply chain (mandatory)

- Use GitHub native attestations: `actions/attest-build-provenance` +
  `actions/attest-sbom`. Current production pin across the yolo-labz rollout is
  v4.1.0, SHA `a2bbfa25375fe432b6a289bc6b6cd05ecd0c4c32`. Pin both actions in
  full SHA-with-comment form, e.g.:
    `uses: actions/attest-build-provenance@a2bbfa25375fe432b6a289bc6b6cd05ecd0c4c32 # v4.1.0`
    `uses: actions/attest-sbom@a2bbfa25375fe432b6a289bc6b6cd05ecd0c4c32 # v4.1.0`
  (the v2/v3/v4 family is acceptable; v4.1.0 is the current rollout standard).
  Do NOT add `slsa-framework/slsa-github-generator` to new work — only maintain
  it on claude-mac-chrome if the SLSA L3 formal claim is still load-bearing.
  New plugins get L2 + native attestations.
- Primary user verification path is `gh attestation verify` (single command, no
  cosign install). Demote `cosign verify-blob` + `slsa-verifier` to an "advanced
  / offline" README section, never the headline.
- Cosign OIDC issuer is `https://token.actions.githubusercontent.com`. The
  `https://github.com/login/oauth` URL is the interactive human flow, NOT CI.
- Publish BOTH CycloneDX 1.7 AND SPDX 2.3 SBOMs. `syft` emits both in one call:
  `syft . -o cyclonedx-json@1.7=sbom.cdx.json -o spdx-json=sbom.spdx.json`. For
  Go repos, additionally run `cyclonedx-gomod app -licenses -std -json` for a
  richer Go-native SBOM.
- Never re-tag a release. `slsa-verifier` validates against the commit SHA at
  signing time; re-tagging produces stale provenance. Cut `vX.Y.Z+1` on botched
  publishes.
- Always `export SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)` before archive or
  build steps so tarballs and wheels are byte-reproducible.

## GitHub Actions hardening (mandatory)

- Pin every action by FULL 40-char commit SHA with a trailing `# vX.Y.Z` comment.
  Tag pins (even "immutable") do NOT satisfy Scorecard's Pinned-Dependencies.
  Dependabot preserves the version comment when bumping SHAs — never strip it.
- Workflow-level `permissions: {}` (deny-all), per-job re-grant. Signing jobs
  need `id-token: write` + `attestations: write` + `contents: read`. Add
  `contents: write` only if the same job cuts a GitHub Release, `packages: write`
  only for OCI pushes.
- Add `step-security/harden-runner@<sha>` in `egress-policy: audit` on every
  release workflow. Flip to `block` after one release cycle once Sigstore egress
  is observed. Linux full-support; macOS/Windows audit-only.
- Use Repository Rulesets, not classic branch protection. Bootstrap required
  checks via `enforcement: disabled` → merge → `active`. Delete classic
  protection AFTER ruleset verification — they stack additively and the stricter
  silently wins.
- Use reusable workflows (`workflow_call`), not composite actions, for shared
  release/signing logic. Caller job must still declare `id-token: write` —
  permissions intersect, not inherit upward.
- Add `zizmor` + `actionlint` as pre-commit hooks. Catches template-injection
  and permission mistakes CodeQL/Sonar miss.
- `persist-credentials: false` on `actions/checkout` unless pushing back.
- `timeout-minutes:` on every job.

## Language-specific (read research.md §3 for full detail)

Go (wa):
- GoReleaser OSS is sufficient; Pro is not needed for this stack.
- `-trimpath`, `-buildvcs=true` (Go 1.24 default), `CGO_ENABLED=0`, `-buildmode=pie`.
- `-ldflags=-X main.date={{.CommitDate}}` — commit timestamp, NEVER `$(date)`.
- Pin toolchain via `go.mod` `toolchain go1.24.x` directive.
- Drop standalone `govulncheck` when adding OSV-Scanner V2 — the latter invokes
  govulncheck internally for Go call-graph reachability; running both is
  redundant.
- `go test -race -shuffle=on -count=1 ./...` in CI; nightly fuzz with committed
  corpus under `testdata/fuzz/`.
- Use `brews:` (not `homebrew_casks:`) for CLIs in the tap.

Python (kokoro-speakd, claude-classroom-submit):
- Publish via PyPI Trusted Publishing (`pypa/gh-action-pypi-publish@release/v1`).
  PEP 740 attestations are auto-generated since v1.11 (Nov 2024). Do NOT add a
  separate `sigstore/gh-action-sigstore-python` step — redundant.
- Build backend: `hatchling` (or `uv_build` for speed). Set `SOURCE_DATE_EPOCH`
  plus `PYTHONHASHSEED=0` before `uv build`.
- Run `pip-audit` + `osv-scanner` + Dependabot in parallel; dedupe on GHSA alias.
- `ruff` replaces flake8/black/isort/pyupgrade/pydocstyle. Use `pyright` over
  mypy unless plugins force the issue.
- CodeQL Python uses `build-mode: none`; add `paths-ignore: ['site-packages/**']`
  for ML-heavy repos.
- kokoro-speakd: declare torch/onnxruntime as `>=` deps — do NOT build/ship your
  own torch wheels. Model weights ship as GitHub Release assets with
  `attest-build-provenance` over the file digest, not via PyPI.
- claude-classroom-submit: publish to PyPI anyway (trusted publishing + PEP 740
  attestations are free benefits even for zero-dep packages).

Shell (claude-mac-chrome):
- `#!/usr/bin/env bash` with bash 3.2 compatibility (macOS). Avoid `declare -A`,
  `mapfile`, `readarray`, `${var^^}`, `${var,,}`.
- CodeQL does NOT support shell in 2026. Upload ShellCheck SARIF separately via
  `github/codeql-action/upload-sarif`.
- Use `bats` + `shellcheck` + `shfmt` (community standard; Anthropic has no
  blessed framework).

## Governance (mandatory)

- `CHANGELOG.md` is auto-generated, never hand-edited. Either tool is acceptable:
  `git-cliff` (single Rust binary, no npm — preferred for Go repos like `wa`) or
  `release-please` (GitHub Action, supports monorepo, preferred for polyglot or
  greenfield plugin repos). Pick one per repo; don't mix. Output format follows
  Keep-a-Changelog 1.1.0.
- Conventional commits enforced via `commitlint` + `@commitlint/config-conventional`
  in `lefthook` (faster than husky; `wa` already uses this — match the pattern).
- Dependency updates: `Dependabot` (native GitHub, preserves `# vX.Y.Z` SHA-pin
  comments) OR `Renovate` (more aggressive, `helpers:pinGitHubActionDigests`
  preset). `wa` uses Renovate — respect existing choice, do not migrate.
- `SECURITY.md` points users at `/security/advisories/new` (GitHub Private
  Vulnerability Reporting). PGP keys are discouraged in 2026.
- `CODEOWNERS` is path-based (documents intent, eases future collaboration).
- DCO sign-off (`git commit -s`) for hygiene; no CLA.
- License: MIT or Apache-2.0, author's choice. `wa` is Apache-2.0 (explicit
  patent grant, matches Anthropic Telegram plugin precedent); other plugins
  are MIT. Do not migrate an existing license without discussion.

## Scorecard optimization

Realistic ceiling for a solo-dev yolo-labz repo is ~8.7/10:

- Fuzzing: `fuzz.yml` is NOT detected by Scorecard. For Go, add one `*_test.go`
  with `func FuzzX(f *testing.F)` — free +10. For shell, restructure to
  `.clusterfuzzlite/` + `.github/workflows/cflite_pr.yml`.
- Contributors: structurally capped ~3/10 for solo devs. Not gameable via
  Co-Authored-By trailers (bots and empty `Company` fields are filtered).
  Accept the loss and document in SECURITY.md.
- Maintained: auto-heals at day 90 with ≥1 commit/week.
- Packaging: add any publishing action (`softprops/action-gh-release`,
  `pypa/gh-action-pypi-publish`, `JS-DevTools/npm-publish`) → 10/10.
- Pinned-Dependencies: use StepSecurity's secure-workflow rewriter
  (https://app.stepsecurity.io/secureworkflow/) for bulk SHA pinning.
- Token-Permissions: `permissions: read-all` at workflow top-level → +2-3.
- Signed-Releases: Sigstore cosign + SLSA provenance assets → 10/10.

## Claude Code plugin ecosystem constraints (informational)

As of April 2026, Anthropic's Claude Code plugin marketplace has NO supply-chain
requirements (no signing, no SBOM, no SLSA, no signature verification on install).
Trust is per-marketplace, not per-plugin. Supply-chain work on yolo-labz plugins
is voluntary — good security hygiene, ahead-of-Anthropic. Do NOT block on
marketplace compliance when planning supply-chain rollouts.

- `plugin.json` lives at `.claude-plugin/plugin.json`; only `name` is required.
- `plugin.json` version field wins over marketplace entry version — pick one home.
- Persistent binary state lives in `CLAUDE_PLUGIN_DATA` (not CLAUDE_PLUGIN_ROOT).
- SessionStart hook pattern: diff a `manifest.lock` against bundled version,
  reinstall binary on drift, `chmod +x`, write new manifest. Do NOT re-download
  every session.
- No plugin-to-plugin dependency field exists; document required sibling plugins
  in README and check via SessionStart hook.
- Shell plugins must use `CLAUDE_PLUGIN_ROOT` for all paths; never bare relative.
- Hooks must exit non-zero with actionable error messages.

## Invariants (never break these)

1. Never re-tag a release. Cut vX.Y.Z+1 on botched publishes.
2. Never commit binaries to the repo (`dist/`, `build/` in `.gitignore`).
3. Never ship a release with failing CI. Tag push must be gated on green main.
4. Never store SonarQube `USER_TOKEN` credentials in CI. Always use
   `PROJECT_ANALYSIS_TOKEN` scoped to one project key.
5. Never use `--certificate-oidc-issuer https://github.com/login/oauth` in cosign
   docs — that is the interactive human flow. Use
   `https://token.actions.githubusercontent.com` for CI-issued OIDC.
6. Never edit `CHANGELOG.md` by hand once `release-please` owns it.
7. Never strip the `# vX.Y.Z` comment from SHA-pinned actions — Dependabot's
   regex needs it to recognize the entry.
8. TRANSITIVE-PIN: a top-level SHA pin is necessary but NOT sufficient. For any
   reusable-workflow / composite-action `uses:`, recursively verify every NESTED
   `uses:` in its call graph is SHA-pinned (it inherits the caller's secrets).
   Enforce with `meta/expand-uses.py --max-depth 5 --fail-on-mutable`.
9. AI-CI-INJECTION self-defense: never combine `pull_request_target`/`workflow_run`
   with a checkout of fork code while secrets are in scope; never interpolate
   `github.event.*` expressions into an agent prompt or a `run:` block (pass via
   `env:`, reference `"$VAR"`); treat agent output as untrusted code (no
   auto-exec/auto-merge). `zizmor --persona=auditor` is a REQUIRED PR gate.
10. OSPS Baseline is the SPEC (Level 1 floor -> Level 2 target); the ~8.7/10
    Scorecard ceiling is only the MEASUREMENT. When they disagree, OSPS wins.
11. AUDIT-BEFORE-BOOTSTRAP: baseline-report -> prioritized plan -> fix-in-PR ->
    re-run Scorecard -> log delta. P0 repo-settings (Code-Review, Branch-Protection,
    Maintained) before P1 automation (SAST, Pinned-Deps, Fuzzing). Fuzzing ships in
    its OWN PR. Never declare a repo "done" on intent — only on a logged delta.
12. Never close the issue/PR yourself (verify + report; the human closes). Frame
    bootstrap/audit runs as an "expert product security engineer"; prefer the `gh`
    CLI over the GitHub MCP on API limits. Weekly drift-audit via `meta/drift-audit.py`
    (a pinned SHA matching no upstream tag, or a SHRINKING tag set, is a probable
    tj-actions-style takeover — treat as P0). Full detail: rules 21-27 of
    `~/NixOS/meta/yolo-labz-release-engineering-research.md`.
