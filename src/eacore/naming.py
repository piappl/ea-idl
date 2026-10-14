"""Column naming convention shared by eacore and eaidl."""

COLUMN_PREFIX = "attr_"


def column_key(name: str) -> str:
    """Return the canonical key for a database column name.

    Lowercasing makes SQLite (``Object_ID``) and PostgreSQL (``object_id``) look the same.
    The ``attr_`` prefix matches the keys eaidl's automap classes have always used.
    """
    return COLUMN_PREFIX + name.lower()
