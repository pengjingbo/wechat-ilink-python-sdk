# wechat-ilink-python-sdk

Python SDK for the WeChat iLink Bot protocol.

## Features

- QR-code login flow for iLink bot accounts
- Async HTTP client for iLink APIs
- Long-polling message loop and dispatch
- Local credential and state persistence
- Example echo bot for quick start

## Requirements

- Python 3.10+

## Installation

Install the published package from PyPI:

```bash
pip install wechat-ilink-sdk
```

The published package exposes the SDK through the `ilink` module:

```python
from ilink import ILinkClient, login_with_qr
```

## Quick Start

Import the public SDK entry points from the `ilink` package:

```python
from ilink import ILinkClient, login_with_qr

print(ILinkClient)
print(login_with_qr)
```

Run the bundled example from a cloned repository:

```bash
python example.py
```

On first run, the bot will ask for QR-code login and cache credentials locally.

## Main Modules

- `ilink.auth`: QR-code login flow
- `ilink.client`: async API client and polling loop
- `ilink.store`: local persistence for credentials and context tokens
- `ilink.types`: protocol models and enums
- `ilink.utils`: helper utilities

## Development

Set up a local development environment with test dependencies:

```bash
uv sync --extra dev
```

Run the test suite through the installed package:

```bash
uv run pytest
```

Build release artifacts locally:

```bash
uv sync --extra release
uv run python -m build
uv run twine check (Get-ChildItem .\dist | ForEach-Object FullName)
```

## Release Automation

Pushes to `main` run the publish workflow in
`.github/workflows/publish.yml`. The workflow runs tests, builds the
distributions, and only uploads to PyPI when the version in
`pyproject.toml` does not already exist on PyPI.

Publishing uses PyPI Trusted Publisher with GitHub OIDC, so no long-lived
PyPI API token is required in GitHub Actions. The repository and PyPI
setup steps are documented in `docs/releasing.md`.
