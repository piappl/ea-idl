import click
from rich import inspect
from eaidl.load import load
from eaidl.utils import load_config


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
def generate(config):
    config = load_config(config)
    model = load(config)
    inspect(model)


if __name__ == "__main__":
    generate()
