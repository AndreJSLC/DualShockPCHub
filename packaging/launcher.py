"""PyInstaller entry point (keeps dshub importable as a package)."""

import sys

from dshub.app import main

if __name__ == "__main__":
    sys.exit(main())
