"""Ensure backend is importable and the agent package initializes first.

Importing the `tools` package triggers a chain that expects `agent` to be
imported first (circular import guard). Import `agent` here so test modules
can simply `from tools.drama_* import ...`.
"""

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import agent  # noqa: E402,F401