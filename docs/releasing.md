# PyPI Release Guide

This project is published manually. Use TestPyPI for the first upload of each
release candidate, then publish the same version to PyPI after verification.

## 1. Bump the version

Update the version in `pyproject.toml` before building release artifacts.

## 2. Install release tooling

```powershell
uv sync --extra release
```

## 3. Build the distributions

```powershell
uv run python -m build
```

Expected output:

- `dist/wechat_ilink_sdk-<version>.tar.gz`
- `dist/wechat_ilink_sdk-<version>-py3-none-any.whl`

## 4. Validate metadata and README rendering

```powershell
uv run twine check dist/*
```

## 5. Verify install from local artifacts

Create a clean virtual environment outside the repository, install the wheel,
and confirm the public import works.

```powershell
py -3.11 -m venv .tmp-release-venv
.\\.tmp-release-venv\\Scripts\\python -m pip install --upgrade pip
.\\.tmp-release-venv\\Scripts\\python -m pip install `
    .\\dist\\wechat_ilink_sdk-<version>-py3-none-any.whl
.\\.tmp-release-venv\\Scripts\\python -c "import ilink; print(ilink.__all__)"
```

Remove the temporary environment when finished.

## 6. Upload to TestPyPI

Set your TestPyPI API token in the current PowerShell session:

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<testpypi-token>"
uv run twine upload --repository testpypi dist/*
```

## 7. Verify the TestPyPI package

In a clean environment, install from TestPyPI and confirm `import ilink`
works. Keep the main PyPI index as an extra source for dependencies.

```powershell
py -3.11 -m venv .tmp-testpypi-venv
.\\.tmp-testpypi-venv\\Scripts\\python -m pip install --upgrade pip
.\\.tmp-testpypi-venv\\Scripts\\python -m pip install `
    --index-url https://test.pypi.org/simple/ `
    --extra-index-url https://pypi.org/simple `
    wechat-ilink-sdk
.\\.tmp-testpypi-venv\\Scripts\\python -c "import ilink; print(ilink.__all__)"
```

## 8. Upload to PyPI

After TestPyPI verification passes, switch to a production PyPI token and
upload the same built artifacts.

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<pypi-token>"
uv run twine upload dist/*
```

## 9. Smoke test the published package

Install the released package from PyPI in a clean environment:

```powershell
py -3.11 -m venv .tmp-pypi-venv
.\\.tmp-pypi-venv\\Scripts\\python -m pip install --upgrade pip
.\\.tmp-pypi-venv\\Scripts\\python -m pip install wechat-ilink-sdk
.\\.tmp-pypi-venv\\Scripts\\python -c "import ilink; print(ilink.__all__)"
```
