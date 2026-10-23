"""Plant harmless startup code in the selected tools root for isolation checks."""
import os
from pathlib import Path
import sys

site = Path(os.environ["PYTHONUSERBASE"]) / "lib" / ("python%d.%d" % sys.version_info[:2]) / "site-packages"
site.mkdir(parents=True, exist_ok=True)
(site / "usercustomize.py").write_text(
    "import os,pathlib; pathlib.Path(os.environ['HOME'], 'auto-python-executed').write_text('ran')\n")
