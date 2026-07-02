"""pytest fixtures and path setup for the plugin's test suite.

Adds the project root's parent directory to ``sys.path`` so that the
package ``astrbot_plugin_ask_user_choice`` (which sits at the project
root without an ``__init__.py``) is importable as a top-level namespace
package. This mirrors how AstrBot loads the plugin at runtime under
``data.plugins.astrobot_plugin_ask_user_choice.<module>``.
"""

import os
import sys

# tests/conftest.py → tests/ → <plugin-dir> → <repo-parent>
_HERE = os.path.dirname(os.path.abspath(__file__))  # tests/
_PLUGIN_DIR = os.path.dirname(_HERE)  # plugin dir (CWD after `cd`)
_PLUGIN_PARENT = os.path.dirname(_PLUGIN_DIR)  # one level above the plugin
if _PLUGIN_PARENT not in sys.path:
    sys.path.insert(0, _PLUGIN_PARENT)
