"""

We can have different types of validators, type is characterize by:

* when in the process it runs (before load, during load, after load)
* what part of model it checks (attribute, class)
* what data it takes in (our models, database rows)

In general we would prefer to run validators before load, and on database rows,
but there we have poor typing and in larger view we care about output, not input.

Some checks might be done much easier after we loaded stuff (as we have real
structure we can search).
"""

import logging
from functools import wraps
from eaidl.config import Configuration
from importlib import import_module

log = logging.getLogger(__name__)


def mod_name(func) -> str:
    # func.__module__ = "eaidl.validation.attributes"
    # func.__name__ = "name_for_reserved_worlds"
    # We want "attributes.name_for_reserved_worlds"
    mod_ = func.__module__.split(".")[-1]
    return f"{mod_}.{func.__name__}"


def validator(func):
    @wraps(func)
    def validator_wrap(config: Configuration, **kwargs):
        if mod_name(func) in config.validators_fail:
            return func(config, **kwargs)
        elif mod_name(func) in config.validators_error:
            try:
                return func(config, **kwargs)
            except ValueError as err:
                log.error(err)
        elif mod_name(func) in config.validators_warn:
            try:
                return func(config, **kwargs)
            except ValueError as err:
                log.warning(err)
        elif mod_name(func) in config.validators_inform:
            try:
                return func(config, **kwargs)
            except ValueError as err:
                log.info(err)

        return

    return validator_wrap


def run(module: str, config: Configuration, **kwargs):
    for item in config.validators_error + config.validators_fail + config.validators_warn + config.validators_inform:
        mod, func = item.split(".")
        if mod == module:
            getattr(import_module(f"eaidl.validation.{mod}"), func)(config, **kwargs)


RESERVED_NAMES = [
    # From python keywords
    # import keyword
    # print(keyword.kwlist)
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
    # IDL
    "abstract",
    "any",
    "attribute",
    "boolean",
    "case",
    "char",
    "component",
    "const",
    "context",
    "custom",
    "default",
    "double",
    "exception",
    "enum",
    "factory",
    "FALSE",
    "fixed",
    "float",
    "in",
    "inout",
    "interface",
    "long",
    "module",
    "native",
    "Object",
    "octet",
    "oneway",
    "out",
    "private",
    "public",
    "raises",
    "readonly",
    "sequence",
    "short",
    "string",
    "struct",
    "supports",
    "switch",
    "TRUE",
    "truncatable",
    "typedef",
    "unsigned",
    "union",
    "ValueBase",
    "valuetype",
    "void",
    "wchar",
    "wstring",
]
