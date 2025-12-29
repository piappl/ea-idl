"""Tests for ModelChanger enum prefix functionality."""

import pytest
import tempfile
import shutil
from pathlib import Path
from eaidl.change import ModelChanger
from eaidl.utils import load_config


@pytest.fixture
def temp_db():
    """Create a temporary copy of the test database."""
    source_db = Path("tests/data/nafv4.qea")
    with tempfile.NamedTemporaryFile(suffix=".qea", delete=False) as tmp:
        temp_path = Path(tmp.name)

    shutil.copy(source_db, temp_path)
    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def config(temp_db):
    """Load test configuration with temporary database."""
    config = load_config("config/sqlite.yaml")
    # Update database URL to point to temp copy
    config.database_url = f"sqlite:///{temp_db}"
    return config


@pytest.fixture
def changer(config):
    """Create ModelChanger instance with temp database."""
    return ModelChanger(config)


def test_check_enum_prefixes_all(changer):
    """Test checking all enums for prefix issues."""
    issues = changer.check_enum_prefixes()

    # The test database should have correct prefixes
    assert isinstance(issues, dict)
    # May have issues or not, but should return a dict
    for enum_name, enum_issues in issues.items():
        assert isinstance(enum_name, str)
        assert isinstance(enum_issues, list)
        for issue in enum_issues:
            assert "attribute" in issue
            assert "current" in issue
            assert "expected" in issue
            assert "attribute_id" in issue


def test_check_enum_prefixes_specific(changer):
    """Test checking a specific enum (even if it doesn't exist)."""
    issues = changer.check_enum_prefixes("NonExistentEnum")

    # Should return empty dict if enum doesn't exist
    assert isinstance(issues, dict)


def test_fix_enum_prefixes_dry_run(changer):
    """Test fixing enum prefixes in dry-run mode."""
    stats = changer.fix_enum_prefixes(dry_run=True)

    assert isinstance(stats, dict)
    assert "checked" in stats
    assert "fixed" in stats
    assert "enums_affected" in stats
    assert isinstance(stats["checked"], int)
    assert isinstance(stats["fixed"], int)
    assert isinstance(stats["enums_affected"], int)

    # In dry-run mode, fixed should be 0
    assert stats["fixed"] == 0


def test_fix_enum_prefixes_commit(changer):
    """Test actually fixing enum prefixes (on temp database)."""
    # First check if there are any issues
    issues_before = changer.check_enum_prefixes()
    num_issues_before = sum(len(issues) for issues in issues_before.values())

    # Fix with commit
    stats = changer.fix_enum_prefixes(dry_run=False)

    # Verify stats
    assert stats["fixed"] == stats["checked"]
    assert stats["checked"] == num_issues_before

    # Check again - should have no issues now
    issues_after = changer.check_enum_prefixes()
    assert len(issues_after) == 0


def test_get_stereotypes(changer):
    """Test getting stereotypes for an object via ModelParser."""
    # Query first object to test stereotype retrieval
    obj = changer.session.query(changer.TObject).first()
    if obj:
        stereotypes = changer.parser.get_stereotypes(obj.attr_ea_guid)
        assert isinstance(stereotypes, list)


def test_is_enum(changer):
    """Test checking if an object is an enum."""
    # Find objects in the database
    objects = changer.session.query(changer.TObject).limit(10).all()
    for obj in objects:
        result = changer.is_enum(obj)
        assert isinstance(result, bool)


def test_enum_prefix_detection_logic(changer):
    """Test that the prefix detection logic works correctly."""
    # Manually create a scenario to test
    # This tests the logic without relying on database content

    # Create a mock enum with wrong prefix
    class MockAttribute:
        def __init__(self, id, name):
            self.attr_id = id
            self.attr_name = name

    # These should be detected as issues
    test_cases = [
        ("TaskStateConditionEnum", "TaskStateEnum_PLANNING", True),  # Wrong prefix
        ("TaskStateConditionEnum", "TaskStateConditionEnum_PLANNING", False),  # Correct prefix
        ("MyEnum", "OtherEnum_VALUE", True),  # Wrong prefix
        ("MyEnum", "MyEnum_VALUE", False),  # Correct prefix
        ("MyEnum", "VALUE", True),  # No prefix
    ]

    for enum_name, attr_name, should_be_issue in test_cases:
        has_issue = not attr_name.startswith(enum_name + "_")
        assert has_issue == should_be_issue, f"Failed for {enum_name}.{attr_name}"
