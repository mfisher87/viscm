# Contributing

Install development dependencies:

```
conda env create  # or `mamba env create`
```


## Development install

```
pip install -e .
```


## Testing the build

```
rm -rf dist
python -m build
pip install dist/*.whl  # or `dist/*.tar.gz`
```


## Code formatting

This codebase uses [black](https://black.readthedocs.io/en/stable/) and
[isort](https://pycqa.github.io/isort/) to automatically format the code.

[`pre-commit`](https://pre-commit.com/) is configured to run them automatically. You can
trigger this manually with `pre-commit run --all-files`.
