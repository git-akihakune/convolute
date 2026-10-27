# PyPI publishing implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this approved plan.

**Goal:** Publish Convolute releases from GitHub Actions using PyPI Trusted Publishing.

**Architecture:** A release event starts a build and validation job. A separate job downloads those distributions and publishes through the `pypi` environment with an OIDC identity.

**Tech Stack:** setuptools, build, Twine, pytest, GitHub Actions, PyPI.

**Spec:** The user-approved publishing instructions in this conversation.

## Constraints

- Keep package name `convolute`, version `0.1.0`, and Python requirement `>=3.11`.
- Include `tests/conftest.py` in the source distribution.
- Use repository `git-akihakune/convolute`, workflow `publish.yml`, and environment `pypi`.
- Install validation tools only in temporary directories and remove them afterward.
- Do not publish a release until the PyPI publisher is configured.

## Task 1: Configure and validate publishing

- [x] Add `MANIFEST.in`, project URLs, and `.github/workflows/publish.yml` as approved.
- [x] Document installation and the one-time publisher configuration.
- [x] Run the existing test suite, build wheel and source distributions, and check them with Twine.
- [x] Verify the source fixture, install the wheel into a fresh environment, and smoke-test the CLI outside the repository.
- [x] Review workflow permissions, trigger, version consistency, and artifact transfer.
- [x] Configure the GitHub environment and prepare reviewed files for push.
- [x] Register the PyPI pending publisher in the user's account, then publish the first release.

## Review focus

The workflow must use a matching PyPI publisher identity; only release publication may upload; failed tests must block uploading; distribution versions must match the release tag; the publishing job must not execute package build code.

## Validation

- All 125 existing tests passed.
- Wheel and source archive built and passed `twine check --strict`.
- Source archive contains `tests/conftest.py`; wheel contains project links and license.
- A fresh wheel installation passed CLI version and dry-run checks outside the repository.
- The workflow's version check accepts `v0.1.0` and rejects `v0.1.1` with the current package version.
- Independent static review found no concrete issues.
- GitHub environment `pypi` exists; the user registered the PyPI pending publisher.
- Release `v0.1.0` was published on 2026-10-27. GitHub Actions run `40586980732` passed both build and publish jobs.
- PyPI serves both `convolute-0.1.0-py3-none-any.whl` and `convolute-0.1.0.tar.gz`.
- A fresh `pipx install convolute==0.1.0` from PyPI passed version and dry-run checks.
