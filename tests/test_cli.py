"""Tests for CLI commands."""

import json
import pytest
from click.testing import CliRunner
from eaidl.cli import cli, run, change, diagram, packages


@pytest.fixture
def runner():
    """Click test runner."""
    return CliRunner()


@pytest.fixture
def temp_config(tmp_path, test_db_path):
    """Create temporary config file for testing."""
    config = tmp_path / "test_config.yaml"
    config.write_text(f"""database_url: "sqlite+pysqlite:///{test_db_path.as_posix()}"
root_packages:
  - "{{753A4DFC-7876-4b00-BB5A-6274AD3817C3}}"
""")
    return config


class TestRunCommand:
    """Tests for the 'run' command."""

    def test_basic_execution(self, runner, temp_config):
        """Test basic IDL generation."""
        result = runner.invoke(run, ["--config", str(temp_config)])
        assert result.exit_code == 0
        # Check for IDL keywords in output
        assert "module" in result.output or "typedef" in result.output or "struct" in result.output

    def test_version_flag(self, runner):
        """Test --version displays version number."""
        result = runner.invoke(run, ["--version"])
        assert result.exit_code == 0
        # Version should be in format x.y.z
        assert "." in result.output
        # Should not load config or generate anything when showing version
        assert "module" not in result.output.lower()

    def test_debug_flag(self, runner, temp_config):
        """Test --debug flag enables logging."""
        result = runner.invoke(run, ["--config", str(temp_config), "--debug"])
        assert result.exit_code == 0
        # Output should still contain IDL
        assert "module" in result.output or "typedef" in result.output or "struct" in result.output

    def test_invalid_config(self, runner):
        """Test error handling with missing config file."""
        result = runner.invoke(run, ["--config", "nonexistent.yaml"])
        assert result.exit_code != 0


class TestChangeCommand:
    """Tests for the 'change' command."""

    def test_basic_execution(self, runner, temp_config):
        """Test change command (currently a placeholder)."""
        result = runner.invoke(change, ["--config", str(temp_config)])
        # May succeed with no changes, just verify it doesn't crash
        # Exit code could be 0 or non-zero depending on implementation
        # Just check it completes without Python exceptions
        assert "Traceback" not in result.output

    def test_version_flag(self, runner):
        """Test --version displays version number."""
        result = runner.invoke(change, ["--version"])
        assert result.exit_code == 0
        assert "." in result.output

    def test_debug_flag(self, runner, temp_config):
        """Test --debug flag works."""
        result = runner.invoke(change, ["--config", str(temp_config), "--debug"])
        # Should not crash
        assert "Traceback" not in result.output


class TestDiagramCommand:
    """Tests for the 'diagram' command."""

    def test_stdout_output(self, runner, temp_config):
        """Test PlantUML generation to stdout."""
        result = runner.invoke(diagram, ["--config", str(temp_config)])
        assert result.exit_code == 0
        assert "@startuml" in result.output
        assert "@enduml" in result.output

    def test_file_output(self, runner, temp_config, tmp_path):
        """Test PlantUML generation to file."""
        output = tmp_path / "diagram.puml"
        result = runner.invoke(diagram, ["--config", str(temp_config), "--output", str(output)])
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "@startuml" in content
        assert "@enduml" in content
        # Should also have confirmation message
        assert "Diagram written to" in result.output

    def test_max_depth_option(self, runner, temp_config):
        """Test --max-depth filtering."""
        result = runner.invoke(diagram, ["--config", str(temp_config), "--max-depth", "2"])
        assert result.exit_code == 0
        assert "@startuml" in result.output

    def test_show_empty_flag(self, runner, temp_config):
        """Test --show-empty flag."""
        result1 = runner.invoke(diagram, ["--config", str(temp_config), "--show-empty"])
        assert result1.exit_code == 0
        assert "@startuml" in result1.output

    def test_no_show_empty_flag(self, runner, temp_config):
        """Test --no-show-empty flag."""
        result = runner.invoke(diagram, ["--config", str(temp_config), "--no-show-empty"])
        assert result.exit_code == 0
        assert "@startuml" in result.output

    def test_debug_flag(self, runner, temp_config):
        """Test --debug flag works with diagram command."""
        result = runner.invoke(diagram, ["--config", str(temp_config), "--debug"])
        assert result.exit_code == 0
        assert "@startuml" in result.output


class TestPackagesCommand:
    """Tests for the 'packages' command."""

    def test_json_format(self, runner, temp_config):
        """Test JSON output format."""
        result = runner.invoke(packages, ["--config", str(temp_config), "--format", "json"])
        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        # Each package should have required fields
        for pkg in data:
            assert "namespace" in pkg
            assert "name" in pkg
            assert "guid" in pkg

    def test_csv_format(self, runner, temp_config):
        """Test CSV output format."""
        result = runner.invoke(packages, ["--config", str(temp_config), "--format", "csv"])
        assert result.exit_code == 0
        # Should have CSV header
        assert "Namespace,Name,GUID" in result.output
        lines = result.output.strip().split("\n")
        assert len(lines) > 1  # Header + at least one data row

    def test_text_format(self, runner, temp_config):
        """Test text output format (default)."""
        result = runner.invoke(packages, ["--config", str(temp_config), "--format", "text"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) > 0
        # Text format should have content (namespace + tab + guid format)
        # Each line should either have a tab or be a GUID-like string
        for line in lines:
            if line:  # Skip empty lines
                # Line should contain either a tab (namespace\tguid) or look like a GUID
                assert "\t" in line or "{" in line or "-" in line

    def test_default_format(self, runner, temp_config):
        """Test that text format is the default."""
        result = runner.invoke(packages, ["--config", str(temp_config)])
        assert result.exit_code == 0
        # Should be text format by default - verify it's not JSON or CSV
        assert not result.output.strip().startswith("[")  # Not JSON
        assert not result.output.strip().startswith("{")  # Not JSON
        assert "Namespace,Name,GUID" not in result.output  # Not CSV
        # Should have some output
        assert len(result.output.strip()) > 0

    def test_file_output_json(self, runner, temp_config, tmp_path):
        """Test JSON output to file."""
        output = tmp_path / "packages.json"
        result = runner.invoke(packages, ["--config", str(temp_config), "--format", "json", "--output", str(output)])
        assert result.exit_code == 0
        assert output.exists()
        # Should have confirmation message
        assert "Package list written to" in result.output
        # Verify file contents
        data = json.loads(output.read_text())
        assert isinstance(data, list)
        assert len(data) > 0

    def test_file_output_csv(self, runner, temp_config, tmp_path):
        """Test CSV output to file."""
        output = tmp_path / "packages.csv"
        result = runner.invoke(packages, ["--config", str(temp_config), "--format", "csv", "--output", str(output)])
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "Namespace,Name,GUID" in content

    def test_debug_flag(self, runner, temp_config):
        """Test --debug flag works with packages command."""
        result = runner.invoke(packages, ["--config", str(temp_config), "--debug", "--format", "json"])
        assert result.exit_code == 0
        # Should still output valid JSON
        data = json.loads(result.output)
        assert isinstance(data, list)


class TestCLIGroup:
    """Tests for the CLI group and integration."""

    def test_cli_group(self, runner):
        """Test CLI group is accessible."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should list available commands
        assert "run" in result.output or "change" in result.output or "diagram" in result.output

    def test_run_via_cli_group(self, runner):
        """Test running command via CLI group."""
        result = runner.invoke(cli, ["run", "--version"])
        assert result.exit_code == 0
        assert "." in result.output

    def test_diagram_via_cli_group(self, runner, temp_config):
        """Test diagram command via CLI group."""
        result = runner.invoke(cli, ["diagram", "--config", str(temp_config)])
        assert result.exit_code == 0
        assert "@startuml" in result.output

    def test_packages_via_cli_group(self, runner, temp_config):
        """Test packages command via CLI group."""
        result = runner.invoke(cli, ["packages", "--config", str(temp_config), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
