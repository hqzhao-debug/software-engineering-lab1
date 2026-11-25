"""Shared source/zipapp entry point for browser UI and CLI commands."""

import sys


def main(argv=None):
    """Keep all existing commands; dispatch the explicit gui subcommand."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "gui":
        from .webapp import main as gui_main

        return gui_main(arguments[1:])
    from .cli import main as cli_main

    return cli_main(arguments)


def run():
    """Preserve exit codes when invoked by zipapp's generated entry module."""
    raise SystemExit(main())
