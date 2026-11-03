"""python -m jarvis entry point."""

import sys

from .cli import main

sys.exit(main(sys.argv[1:]))
