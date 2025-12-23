import click
import json
import logging
from functools import wraps
from eaidl.load import ModelParser
from eaidl.change import ModelChanger
from eaidl.utils import load_config, LogFormatter, flatten_packages
from eaidl.generate import generate
from eaidl.diagram import PackageDiagramGenerator

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
        logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=[log_handler])

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
@setup_command
def change(config_obj, debug):
    """Apply changes to EA model."""
    changer = ModelChanger(config_obj)
    changer.change()


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
    all_packages = flatten_packages(model)

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
    all_packages = flatten_packages(model)

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


cli.add_command(run)
cli.add_command(change)
cli.add_command(diagram)
cli.add_command(packages)

if __name__ == "__main__":
    cli()
