# Security

Report suspected vulnerabilities in the SDK or in how it is distributed to PulpoAR privately: use this repository's
**Security → Report a vulnerability** form on GitHub, or tell your PulpoAR contact. Please do not open a public issue.

## Verifying what you download

Compare a file's SHA-256 with the `.sha256` file next to it and with the release's recorded manifest in this
repository, `releases/<product>/<version>.json` (`releases/<version>.json` for releases up to Try-On 0.2.0 and SkinAI
0.2.0-rc.1). `scripts/verify_release.py <version> --product <tryon|skinai>` does both. A difference is a reason to stop and tell us. Published versions are never
changed: a fix is always a new version.
