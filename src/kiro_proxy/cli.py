"""CLI 格式化工具。"""

import click


class CLIFormatter:
    """CLI 输出格式化。"""

    @staticmethod
    def success(message: str):
        click.echo(click.style(f"✓ {message}", fg="green"))

    @staticmethod
    def error(message: str):
        click.echo(click.style(f"✗ {message}", fg="red"))

    @staticmethod
    def warning(message: str):
        click.echo(click.style(f"⚠ {message}", fg="yellow"))

    @staticmethod
    def info(message: str):
        click.echo(click.style(f"ℹ {message}", fg="blue"))
