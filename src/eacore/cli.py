"""Command line interface: ``eacore``."""

import click


@click.group()
def cli() -> None:
    """Inspect, compare and check Enterprise Architect repositories."""
