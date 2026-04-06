# PyPI Release Guide

This project publishes from GitHub Actions on pushes to `main`. The release
workflow lives at `.github/workflows/publish.yml` and uses PyPI Trusted
Publisher with GitHub OIDC instead of a long-lived PyPI API token.

## 1. Configure PyPI Trusted Publisher

In the PyPI project settings for `wechat-ilink-sdk`, add a Trusted Publisher
for this repository:

- Owner: `pengjingbo`
- Repository: `wechat-ilink-python-sdk`
- Workflow: `.github/workflows/publish.yml`

PyPI's setup flow for GitHub Actions is documented at
<https://docs.pypi.org/trusted-publishers/adding-a-publisher/>.

## 2. Bump the version

Update the version in `pyproject.toml` before merging to `main`. The publish
workflow treats the version as the release gate and skips uploading if that
version is already present on PyPI.

## 3. Install release tooling

```powershell
uv sync --extra release
```

## 4. Run local verification

```powershell
uv run pytest
uv run python -m build
uv run twine check (Get-ChildItem .\dist | ForEach-Object FullName)
```

Expected output:

- `dist/wechat_ilink_sdk-<version>.tar.gz`
- `dist/wechat_ilink_sdk-<version>-py3-none-any.whl`

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

## 6. Merge to `main`

After local verification passes, merge the version bump and changelog/docs
updates into `main`. GitHub Actions will:

- install dependencies with `uv`
- run `pytest`
- build the sdist and wheel
- run `twine check`
- upload to PyPI if the target version is not already published

You can also trigger the same workflow manually with `workflow_dispatch`.

## 7. Smoke test the published package

Once the GitHub Actions publish job succeeds, verify the released package from
PyPI in a clean environment:

```powershell
py -3.11 -m venv .tmp-pypi-venv
.\\.tmp-pypi-venv\\Scripts\\python -m pip install --upgrade pip
.\\.tmp-pypi-venv\\Scripts\\python -m pip install wechat-ilink-sdk
.\\.tmp-pypi-venv\\Scripts\\python -c "import ilink; print(ilink.__all__)"
```
