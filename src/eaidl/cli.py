import click
import logging
from eaidl.load import ModelParser
from eaidl.utils import load_config, LogFormatter
from eaidl.generate import generate

log = logging.getLogger(__name__)


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
def run(config, debug):
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(LogFormatter())
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=[log_handler])
    log.debug("Debug mode")
    config = load_config(config)
    parser = ModelParser(config)
    model = parser.load()
    print(generate(config, model))


if __name__ == "__main__":
    run()
