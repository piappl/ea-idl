# eaidl

This is replacement for [idl4-enterprise-architect](https://github.com/rticommunity/idl4-enterprise-architect),
but not as plugin, but rather something that can be run as part of CI against database.
Similar in concepts in [pyMDG](https://github.com/Semprini/pyMDG).



## setup environment


```sh
pyenv update
pyenv install 3.13
pyenv virtualenv 
pyenv virtualenv 3.13 eaidl
```

```sh
pip install -e "."
pytest 
```