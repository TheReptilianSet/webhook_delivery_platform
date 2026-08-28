# Container Security Verification — 2026-08-28

## Trigger

GitHub Actions run `33155468928` passed dependency audit and filesystem scanning but failed the
runtime image scan. A local scan of the same image with Trivy 0.70.0 reproduced five HIGH findings:

- `CVE-2026-14456` in three Debian OpenSSL packages at `3.5.6-1~deb13u2`;
- `GHSA-6v7p-g79w-8964` in the `msgpack` copy vendored by system pip;
- `CVE-2025-47273` in the `setuptools` copy vendored by system pip.

The application virtual environment did not contain `msgpack` or `setuptools`. Both findings came
from the system pip toolchain supplied by the Python base image, which is not needed at runtime.

## Changes

- The runtime stage applies available Debian package upgrades and removes apt metadata.
- System pip and its vendored packages are removed after the application virtual environment has
  been built.
- CI image builds disable third-party build attestations for this scan so Trivy inventories the
  final runtime filesystem directly.
- The Trivy gate remains `HIGH,CRITICAL`, uses `ignore-unfixed`, and exits non-zero on findings.

## Results

| Check | Result |
| --- | --- |
| Runtime image build with CI flags | Passed |
| OpenSSL packages | `3.5.7-1~deb13u2` |
| System pip absent | Passed |
| Application import from runtime image | Passed |
| `docker build --check .` | Passed, no warnings |
| Trivy 0.70.0 image vulnerability and secret scan | Passed, no HIGH/CRITICAL findings or secrets |

The local Trivy command used the same scanners, severity threshold, unfixed policy, and exit code as
the GitHub Actions image scan. A new GitHub Actions run remains required to confirm the hosted runner
path.
