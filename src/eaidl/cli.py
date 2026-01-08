import click
import json
import logging
from pathlib import Path
from functools import wraps
from eaidl.load import ModelParser
from eaidl.change import ModelChanger
from eaidl.utils import load_config, LogFormatter
from eaidl.tree_utils import collect_packages
from eaidl.generate import generate
from eaidl.diagram import PackageDiagramGenerator
from eaidl.html_export import export_html
from eaidl.transforms import flatten_abstract_classes
from eaidl.json_schema_importer import JsonSchemaImporter

log = logging.getLogger(__name__)


def setup_command(func):
    """Decorator to handle common CLI setup (logging, config loading, version)."""

    @wraps(func)
    def wrapper(config, debug, version=None, **kwargs):
        # Handle --version flag
        if version is not None and version:
            import tomllib

            with open("pyproject.toml", "rb") as f:
                data = tomllib.load(f)
            click.echo(data["project"]["version"])
            return

        # Setup logging
        log_handler = logging.StreamHandler()
        log_handler.setFormatter(LogFormatter())
        logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=[log_handler])

        # Load config
        config_obj = load_config(config)
        if debug:
            log.debug(json.dumps(config_obj.model_dump(), indent=4))

        # Call actual command with config_obj
        return func(config_obj=config_obj, debug=debug, **kwargs)

    return wrapper


@click.group()
def cli():
    pass


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--version", is_flag=True, help="Show the application's version.")
@setup_command
def run(config_obj, debug):
    """Generate IDL from EA model."""
    parser = ModelParser(config_obj)
    model = parser.load()
    print(generate(config_obj, model))


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--version", is_flag=True, help="Show the application's version.")
@click.option("--check-enum-prefixes", is_flag=True, help="Check enum attribute prefixes for correctness.")
@click.option("--fix-enum-prefixes", is_flag=True, help="Fix enum attribute prefixes to match enum name.")
@click.option("--enum-name", default=None, help="Specific enum name to check/fix (default: all enums).")
@click.option("--dry-run/--no-dry-run", default=True, help="Dry run mode (show changes without committing).")
@setup_command
def change(config_obj, debug, version, check_enum_prefixes, fix_enum_prefixes, enum_name, dry_run):
    """Make bulk changes to EA model database (enums, connectors, etc.)."""
    changer = ModelChanger(config_obj)

    if check_enum_prefixes:
        issues = changer.check_enum_prefixes(enum_name)
        if not issues:
            click.echo("✓ All enum prefixes are correct!")
        else:
            click.echo(f"Found prefix issues in {len(issues)} enum(s):\n")
            for enum, enum_issues in issues.items():
                click.echo(f"Enum: {enum}")
                for issue in enum_issues:
                    click.echo(f"  {issue['current']} -> {issue['expected']}")
                click.echo()
            click.echo(f"Total: {sum(len(e) for e in issues.values())} attributes need correction")
            if not fix_enum_prefixes:
                click.echo("\nRun with --fix-enum-prefixes to apply changes")
    elif fix_enum_prefixes:
        stats = changer.fix_enum_prefixes(enum_name, dry_run=dry_run)
        if dry_run:
            click.echo(
                f"\nDry run complete: would fix {stats['checked']} attributes in {stats['enums_affected']} enums"
            )
            click.echo("Run with --no-dry-run to apply changes")
        else:
            click.echo(f"✓ Fixed {stats['fixed']} attributes in {stats['enums_affected']} enums")
    else:
        # Run custom change() method
        changer.change()
        click.echo("✓ Custom changes completed")


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--output", default=None, help="Output file path (default: stdout).")
@click.option("--max-depth", default=None, type=int, help="Maximum package nesting depth to show.")
@click.option("--show-empty/--no-show-empty", default=True, help="Include packages with no classes.")
@setup_command
def diagram(config_obj, debug, output, max_depth, show_empty):
    """Generate a PlantUML diagram of package structure and dependencies."""
    parser = ModelParser(config_obj)
    model = parser.load()

    # Flatten all packages for diagram generation
    all_packages = collect_packages(model)

    # Generate diagram
    generator = PackageDiagramGenerator(
        packages=all_packages,
        get_all_depends_on=parser.get_all_depends_on,
        get_all_class_id=parser.get_all_class_id,
        max_depth=max_depth,
        show_empty=show_empty,
    )

    diagram_content = generator.generate_plantuml()

    if output:
        with open(output, "w") as f:
            f.write(diagram_content)
        click.echo(f"Diagram written to {output}")
    else:
        click.echo(diagram_content)


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--output", default=None, help="Output file path (default: stdout).")
@click.option(
    "--format", type=click.Choice(["json", "csv", "text"], case_sensitive=False), default="text", help="Output format."
)
@setup_command
def packages(config_obj, debug, output, format):
    """Generate a list of package names (namespaced) and package GUIDs."""
    parser = ModelParser(config_obj)
    model = parser.load()

    # Flatten all packages
    all_packages = collect_packages(model)

    # Generate output based on format
    if format == "json":
        package_list = [
            {"namespace": "::".join(pkg.namespace), "name": pkg.name, "guid": pkg.guid} for pkg in all_packages
        ]
        output_content = json.dumps(package_list, indent=2)
    elif format == "csv":
        import csv
        from io import StringIO

        output_stream = StringIO()
        writer = csv.writer(output_stream)
        writer.writerow(["Namespace", "Name", "GUID"])
        for pkg in all_packages:
            writer.writerow(["::".join(pkg.namespace), pkg.name, pkg.guid])
        output_content = output_stream.getvalue()
    else:  # text format
        lines = []
        for pkg in all_packages:
            namespaced_name = "::".join(pkg.namespace)
            lines.append(f"{namespaced_name}\t{pkg.guid}")
        output_content = "\n".join(lines)

    if output:
        with open(output, "w") as f:
            f.write(output_content)
        click.echo(f"Package list written to {output}")
    else:
        click.echo(output_content)


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--output", default="./_docs", help="Output directory for HTML documentation.")
@click.option("--no-diagrams", is_flag=True, help="Skip diagram generation.")
@setup_command
def docs(config_obj, debug, output, no_diagrams):
    """Generate interactive HTML documentation from EA model."""
    parser = ModelParser(config_obj)
    model = parser.load()

    # Apply transformations (same as run command)
    if config_obj.flatten_abstract_classes:
        flatten_abstract_classes(model)

    # Export HTML documentation
    output_path = Path(output)
    export_html(config_obj, model, output_path)

    click.echo(f"✓ HTML documentation generated in {output_path}")
    click.echo(f"  Open {output_path / 'index.html'} in your browser")


@click.command()
@click.option("--config", required=True, help="Configuration file with database connection.")
@click.option("--schema", required=True, help="Path to JSON schema file.")
@click.option("--package", default="imported_schema", help="Root package name for imported schema.")
@click.option("--debug", is_flag=True, help="Enable debug logging.")
@setup_command
def import_schema(config_obj, schema, package, debug):
    """Import JSON schema into EA database as IDL structures."""
    importer = JsonSchemaImporter(config_obj, schema, package)
    model_package = importer.parse_schema()
    importer.import_to_database(model_package)
    click.echo(f"✓ Imported {schema} as package '{package}'")
    click.echo(f"  Created {len(model_package.classes)} classes")


@click.command()
@click.option("--config", required=True, help="Configuration file.")
@click.option("--output", required=True, help="Output DOCX file path.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@setup_command
def export_notes(config_obj, debug, output):
    """Export EA model notes to DOCX format for editing."""
    from eaidl.notes_export import NotesCollector, DocxExporter

    # Load model
    parser = ModelParser(config_obj)
    packages = parser.load()

    # Collect notes
    click.echo("Collecting notes from model...")
    collector = NotesCollector(config_obj, packages)
    notes_export = collector.collect_all_notes()

    # Export to DOCX
    click.echo(f"Exporting {len(notes_export.notes)} notes to {output}...")
    exporter = DocxExporter(notes_export)
    exporter.export_to_file(output)

    click.echo(f"✓ Successfully exported {len(notes_export.notes)} notes to {output}")


@click.command()
@click.option("--config", required=True, help="Configuration file.")
@click.option("--input", required=True, help="Input DOCX file path.")
@click.option("--dry-run/--no-dry-run", default=True, help="Dry run (no database changes).")
@click.option("--strict", is_flag=True, help="Fail on any checksum mismatch.")
@click.option("--report", default=None, help="Save detailed report to file (JSON).")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@setup_command
def import_notes(config_obj, debug, input, dry_run, strict, report):
    """Import edited notes from DOCX back to EA database."""
    from eaidl.notes_import import DocxImporter
    import json

    # Load model parser (for database access)
    parser = ModelParser(config_obj)
    parser.load()  # Initialize session

    # Parse DOCX
    click.echo(f"Parsing notes from {input}...")
    importer = DocxImporter(input, config_obj, parser)
    parsed_notes = importer.parse_document()
    click.echo(f"Parsed {len(parsed_notes)} notes from document")

    # Validate and import
    mode = "DRY RUN" if dry_run else "LIVE IMPORT"
    click.echo(f"\n{mode}: Validating and importing notes...")
    summary = importer.validate_and_import(parsed_notes, dry_run=dry_run, strict=strict)

    # Print summary
    summary.print_report()

    # Save detailed report if requested
    if report:
        report_data = {
            "total_notes": summary.total_notes,
            "imported": summary.imported,
            "skipped_checksum": summary.skipped_checksum,
            "skipped_unchanged": summary.skipped_unchanged,
            "not_found": summary.not_found,
            "errors": summary.errors,
            "results": [
                {
                    "note_type": r.note_type,
                    "path": r.path,
                    "status": r.status.value,
                    "message": r.message,
                }
                for r in summary.results
            ],
        }
        with open(report, "w") as f:
            json.dump(report_data, f, indent=2)
        click.echo(f"\n📄 Detailed report saved to {report}")


cli.add_command(run)
cli.add_command(change)
cli.add_command(diagram)
cli.add_command(packages)
cli.add_command(docs)
cli.add_command(import_schema)
cli.add_command(export_notes)
cli.add_command(import_notes)

if __name__ == "__main__":
    cli()
