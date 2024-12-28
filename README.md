# eaidl

This is replacement for [idl4-enterprise-architect](https://github.com/rticommunity/idl4-enterprise-architect),
but not as plugin, but rather something that can be run as part of CI against database.
Similar in concepts in [pyMDG](https://github.com/Semprini/pyMDG), but we have some different assumptions on model structure.


## setup environment


```sh
# This example uses pyenv, use whatever you prefer
pyenv update
pyenv install 3.13
pyenv virtualenv
pyenv virtualenv 3.13 eaidl
```

```sh
# Development mode install
pip install -e "."
# We use pre-commit hook
pre-commit install
pytest
```

## run

There are sample configuration files provided in [config](./config/).

```sh
# This should run against sample SQLite database in unit tests:
eaidl --config config/sqlite.yaml
# This needs custom postgresql configuration to run
eaidl --config config/postgres.yaml > res.idl
```
