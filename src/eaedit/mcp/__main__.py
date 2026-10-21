"""``python -m eaedit.mcp MODEL.qea [options]``: the same as the ``eaedit-mcp`` command.

For hosts where console-script launchers do not work (for example a copied virtual environment), this starts the
server with the interpreter alone.
"""

from eaedit.mcp.server import main

main()
