import click
import json
import logging
from eaidl.load import ModelParser
from eaidl.change import ModelChanger
from eaidl.utils import load_config, LogFormatter
from eaidl.generate import generate

log = logging.getLogger(__name__)


@click.group()
def cli():
    pass


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
def run(config, debug):
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
def change(config, debug):
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(LogFormatter())
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=[log_handler])
    config = load_config(config)
    if debug:
        log.debug(json.dumps(config.model_dump(), indent=4))
    changer = ModelChanger(config)
    changer.change()


cli.add_command(run)
cli.add_command(change)

if __name__ == "__main__":
    cli()
