# Releasing

The `publish.yml` GitHub Actions workflow tests, builds, validates, and publishes
the package when a GitHub release is published. Uploading uses PyPI Trusted
Publishing, with no API token stored in the repository.

One-time setup:

1. Create a PyPI account, verify its email address, and enable two-factor
   authentication.
2. Create the `pypi` environment in this repository's GitHub settings.
3. At <https://pypi.org/manage/account/publishing/>, register a pending publisher:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `convolute` |
   | Owner | `git-akihakune` |
   | Repository | `convolute` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

For each release, update both `pyproject.toml` and `src/convolute/__init__.py`
to the same version, commit and push the changes, then publish a GitHub release
with a matching tag such as `v0.1.0`. The workflow rejects mismatched versions
before building. The first successful upload creates the PyPI project; a pending
publisher does not reserve its name. Subsequent releases need a new version.
