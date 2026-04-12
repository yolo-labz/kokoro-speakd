# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

Please use **GitHub Private Vulnerability Reporting**:
https://github.com/yolo-labz/kokoro-speakd/security/advisories/new

Solo maintainer; best-effort SLA: acknowledge within 5 business days,
patch or mitigation within 30 days for High/Critical.

Do NOT open public issues for vulnerabilities.

## Supply Chain Verification

All releases are signed via Sigstore and attested with build provenance.
Verify downloaded artifacts with:

```bash
gh attestation verify ./<artifact> \
  --repo yolo-labz/kokoro-speakd \
  --signer-workflow yolo-labz/kokoro-speakd/.github/workflows/release.yml
```
