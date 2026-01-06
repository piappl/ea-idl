#!/usr/bin/env python3
"""Find EA notes that contain HTML markup."""

from eaidl.utils import load_config
from eaidl.load import ModelParser

config = load_config("config/sqlite.yaml")
parser = ModelParser(config)
packages = parser.load()


def find_html_notes(obj, obj_type, path=""):
    """Recursively find notes with HTML."""

    if obj_type == "package":
        current_path = f"{path}/{obj.name}" if path else obj.name

        if obj.notes and ("<" in obj.notes or ">" in obj.notes):
            print(f"\nPACKAGE: {current_path}")
            print("Note content:")
            print(obj.notes)
            print("-" * 80)

        for cls in obj.classes:
            find_html_notes(cls, "class", current_path)

        for child in obj.packages:
            find_html_notes(child, "package", current_path)

    elif obj_type == "class":
        current_path = f"{path}/{obj.name}"

        if obj.notes and ("<" in obj.notes or ">" in obj.notes):
            print(f"\nCLASS: {current_path}")
            print("Note content:")
            print(obj.notes)
            print("-" * 80)

        for attr in obj.attributes:
            if attr.notes and ("<" in attr.notes or ">" in attr.notes):
                print(f"\nATTRIBUTE: {current_path}/{attr.name}")
                print("Note content:")
                print(attr.notes)
                print("-" * 80)


# Search all packages
count = 0
for pkg in packages:
    find_html_notes(pkg, "package")
    count += 1
    if count >= 5:  # Limit search
        break
