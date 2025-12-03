# eaidl

This is replacement for [idl4-enterprise-architect](https://github.com/rticommunity/idl4-enterprise-architect),
but not as plugin, but rather something that can be run as part of CI against database.
Similar in concepts in [pyMDG](https://github.com/Semprini/pyMDG), but we have some different [assumptions on model structure](./MODEL.md).

For detailed code structure documentation, see [STRUCTURE.md](./STRUCTURE.md).


## setup environment

### Using uv (recommended)

```sh
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies including dev tools (pytest, ruff, pre-commit)
uv sync --extra dev

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest
```

### Alternative: Using pyenv

```sh
# This example uses pyenv
pyenv update
pyenv install 3.13
pyenv virtualenv 3.13 eaidl
pyenv activate eaidl

# Development mode install
pip install -e "."
# We use pre-commit hook
pre-commit install
pytest
```

## run

### with installed

There are sample configuration files provided in [config](./config/).

```sh
# This should run against sample SQLite database in unit tests:
eaidl --config config/sqlite.yaml
# This needs custom postgresql configuration to run
eaidl --config config/postgres.yaml > res.idl
```
### using uvx

```sh
uvx --with sqlite --from git+https://github.com/piappl/ea-idl/ eaidl --config config/sqlite.yaml
uvx --with psycopg2 --from git+https://github.com/piappl/ea-idl/ eaidl --config config/postgres.yaml
```


## Regenerate docs

```sh
cd scripts
./export_diagrams.sh --model /home/${USER}/git/4817/ea-idl/tests/data/nafv4.qea  --output /tmp
# rm -r ../docs/images/{data,message}
cp -r /tmp/Model/core/* ../docs/images
```
