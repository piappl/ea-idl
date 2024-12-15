import click
from eaidl.load import ModelParser
from eaidl.utils import load_config
from eaidl.generate import generate


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
def run(config):
    config = load_config(config)
    parser = ModelParser(config)
    model = parser.load()
    ret = generate(config, model)
    print(ret)


if __name__ == "__main__":
    run()
