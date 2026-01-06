#!/usr/bin/env python3
"""Inspect existing EA notes to see what format they use."""

from eaidl.utils import load_config
from eaidl.load import ModelParser

config = load_config("config/sqlite.yaml")
parser = ModelParser(config)
packages = parser.load()


def inspect_notes(obj, obj_type, indent=0):
    """Recursively inspect notes."""
    prefix = "  " * indent

    if obj_type == "package":
        if obj.notes:
            print(f"\n{prefix}PACKAGE: {obj.name}")
            print(f"{prefix}Note content (first 500 chars):")
            print(f"{prefix}{obj.notes[:500]}")
            print(f"{prefix}...")

        for cls in obj.classes:
            inspect_notes(cls, "class", indent + 1)

        for child in obj.packages:
            inspect_notes(child, "package", indent + 1)

    elif obj_type == "class":
        if obj.notes:
            print(f"\n{prefix}CLASS: {obj.name}")
            print(f"{prefix}Note content (first 500 chars):")
            print(f"{prefix}{obj.notes[:500]}")
            print(f"{prefix}...")


# Inspect first few packages
for i, pkg in enumerate(packages[:3]):
    inspect_notes(pkg, "package")
    if i >= 2:  # Limit output
        break
