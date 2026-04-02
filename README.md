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
- Recommended workflow: `uv`

## Installation

```bash
uv sync
```

Or install the package dependencies with your preferred Python environment tool.

## Project Structure

- `src/ilink/`: core SDK implementation
- `tests/`: test suite
- `example.py`: runnable echo bot example
- `pyproject.toml`: project metadata and dependency configuration
- `AGENTS.md`: lightweight project structure notes

## Quick Start

Run the example bot:

```bash
uv run python example.py
```

On first run, the bot will ask for QR-code login and cache credentials locally.

## Main Modules

- `ilink.auth`: QR-code login flow
- `ilink.client`: async API client and polling loop
- `ilink.store`: local persistence for credentials and cursors
- `ilink.types`: protocol models and enums
- `ilink.utils`: helper utilities

## Testing

```bash
pytest
```
