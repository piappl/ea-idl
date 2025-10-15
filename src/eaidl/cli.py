import click
import json
import logging
from eaidl.load import ModelParser
from eaidl.change import ModelChanger
from eaidl.utils import load_config, LogFormatter
from eaidl.generate import generate
from eaidl.diagram import PackageDiagramGenerator

log = logging.getLogger(__name__)


@click.group()
def cli():
    pass


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--version", is_flag=True, help="Show the application's version.")
def run(config, debug, version):
    if version:
        import toml

        with open("pyproject.toml", "r") as f:
            data = toml.load(f)
        click.echo(data["project"]["version"])
        return

    log_handler = logging.StreamHandler()
    log_handler.setFormatter(LogFormatter())
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=[log_handler])
    config = load_config(config)
    if debug:
        log.debug(json.dumps(config.model_dump(), indent=4))
    parser = ModelParser(config)
    model = parser.load()
    print(generate(config, model))


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--version", is_flag=True, help="Show the application's version.")
def change(config, debug, version):
    if version:
        import toml

        with open("pyproject.toml", "r") as f:
            data = toml.load(f)
        click.echo(data["project"]["version"])
        return

    log_handler = logging.StreamHandler()
    log_handler.setFormatter(LogFormatter())
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=[log_handler])
    config = load_config(config)
    if debug:
        log.debug(json.dumps(config.model_dump(), indent=4))
    changer = ModelChanger(config)
    changer.change()


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--output", default=None, help="Output file path (default: stdout).")
@click.option("--max-depth", default=None, type=int, help="Maximum package nesting depth to show.")
@click.option("--show-empty/--no-show-empty", default=True, help="Include packages with no classes.")
def diagram(config, debug, output, max_depth, show_empty):
    """Generate a PlantUML diagram of package structure and dependencies."""
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(LogFormatter())
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=[log_handler])

    config_obj = load_config(config)
    if debug:
        log.debug(json.dumps(config_obj.model_dump(), indent=4))

    parser = ModelParser(config_obj)
    model = parser.load()

    # Flatten all packages for diagram generation
    def flatten_packages(packages):
        result = []
        for pkg in packages:
            result.append(pkg)
            result.extend(flatten_packages(pkg.packages))
        return result

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


cli.add_command(run)
cli.add_command(change)
cli.add_command(diagram)

if __name__ == "__main__":
    cli()
