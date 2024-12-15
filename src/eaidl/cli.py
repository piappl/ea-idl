import click
from eaidl.load import load
from eaidl.utils import load_config
from eaidl.generate import generate


@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
def run(config):
    config = load_config(config)
    model = load(config)
    ret = generate(config, model)
    print(ret)


if __name__ == "__main__":
    run()
