"""Provider adapter package (R1).

Modules in this directory call registry.register(...) at import time.
Business code (drama_video / drama_i2v / drama_lip) dispatches through
registry.dispatch(...). Adding a new model = add a module here.

The package is auto-loaded on startup; see tools/loader.py.
"""