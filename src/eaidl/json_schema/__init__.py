"""JSON Schema to EA-IDL import module.

This module provides functionality to import JSON Schema files into EA databases,
converting JSON schema types to IDL structures with proper stereotypes.

The import process is split across multiple modules for better maintainability:
- type_utils.py: Type mapping and name conversion utilities
- The main JsonSchemaImporter class remains in the parent module for now
"""

# Re-export the main importer for backward compatibility
from eaidl.json_schema_importer import JsonSchemaImporter

__all__ = ["JsonSchemaImporter"]
