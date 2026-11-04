# -*- coding: utf-8 -*-
"""python -m jobpilot 等价于 python -m jobpilot.cli。"""
import sys

from jobpilot.cli import main

if __name__ == "__main__":
    sys.exit(main())