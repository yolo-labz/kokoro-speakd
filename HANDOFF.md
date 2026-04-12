# Release Engineering Handoff — kokoro-speakd

**Date:** 2026-04-12
**PR merged:** #1 (feat: CI + supply-chain bootstrap)
**Tag pushed:** v0.1.1 (first CI-bootstrapped release; v0.1.0 was pre-CI)
**Session:** NixOS repo rollout — 6-agent research + parallel execution

## What was shipped (greenfield bootstrap)

- **CI workflow** — ruff lint, ruff format, pyright typecheck, pytest (12 smoke tests for markdown.py)
- **Release workflow** — `uv build` with SOURCE_DATE_EPOCH + PYTHONHASHSEED=0, `actions/attest-build-provenance@v2`, CycloneDX + SPDX SBOMs via anchore/sbom-action, PyPI trusted publish via `pypa/gh-action-pypi-publish`, harden-runner audit mode
- **CodeQL** (Python + Actions, build-mode: none, security-extended) — weekly + push + PR
- **OSV-Scanner** — weekly + PR
- **Scorecard** — weekly, SARIF upload
- **SonarQube** — gracefully skips when SONAR_TOKEN not set (project not yet provisioned)
- **Dependabot** — pip + github-actions, weekly, grouped
- **pyproject.toml** — hatchling backend, torch>=2.0, onnxruntime>=1.16, ruff+pyright config
- **SECURITY.md**, **CODEOWNERS**, **CONTRIBUTING.md**, **pull_request_template.md**
- **tests/test_markdown.py** — 12 smoke tests
- **.pre-commit-config.yaml** — ruff + pyright hooks
- **CLAUDE.md** — created from scratch with ML daemon rules
- All actions SHA-pinned, top-level `permissions: {}`, `persist-credentials: false`, `timeout-minutes`
- Existing code cleaned: 13 ruff errors + 4 pyright errors fixed
- Branch protection enabled (PR review + linear history + no force push)
- Private Vulnerability Reporting enabled

## Pending manual steps

1. **SonarQube project** — create `yolo-labz_kokoro-speakd` on `sonarqube.home301server.com.br`, generate PROJECT_ANALYSIS_TOKEN, set via:
   ```
   gh secret set SONAR_TOKEN --repo yolo-labz/kokoro-speakd --body "<token>"
   ```
2. **PyPI Trusted Publisher** — on pypi.org, create project `kokoro-speakd`, add pending publisher: owner=yolo-labz, repo=kokoro-speakd, workflow=release.yml, environment=pypi
3. **Add required status checks** — after first main run: `lint`, `typecheck`, `test`, `CodeQL`, `scan` (scorecard + osv)
4. **Model weights release asset** — separate workflow to upload kokoro model weights with attestation (not in this PR, planned for next feature)

## Source of truth

- Research: `~/NixOS/meta/yolo-labz-release-engineering-research.md`
- Plan: `~/NixOS/meta/yolo-labz-release-engineering-plan.md`
- Global rule: `plugin-release-engineering` in `~/NixOS/modules/home/claude-code.nix`
- ML daemon specifics: research §3.2 + §9.3
