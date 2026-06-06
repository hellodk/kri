"""#439: react and react-dom MUST be the same version.

React 19 throws error #527 ("Incompatible React versions") at init and the UI
never mounts when react != react-dom. A dependabot bump of react alone (19.2.7)
that left react-dom behind (19.2.6) took the whole UI down. This guard fails the
build if the two ever diverge again — in the declared package.json ranges OR in
the resolved pnpm-lock.yaml versions.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
PKG = ROOT / "frontend/package.json"
LOCK = ROOT / "frontend/pnpm-lock.yaml"


def _declared(pkg: dict, name: str) -> str:
    """Return the package.json version range with any leading ^ or ~ stripped."""
    raw = pkg["dependencies"][name]
    return raw.lstrip("^~")


def test_package_json_react_and_react_dom_match():
    pkg = json.loads(PKG.read_text())
    assert _declared(pkg, "react") == _declared(pkg, "react-dom"), (
        f"react ({pkg['dependencies']['react']}) and react-dom "
        f"({pkg['dependencies']['react-dom']}) must declare the same version"
    )


def test_lockfile_resolves_react_and_react_dom_to_same_version():
    text = LOCK.read_text()
    # Top-level package keys look like:  react@19.2.7:  /  react-dom@19.2.6:
    react = re.search(r"^  '?react@(\d+\.\d+\.\d+)'?:", text, re.MULTILINE)
    react_dom = re.search(r"^  '?react-dom@(\d+\.\d+\.\d+)'?:", text, re.MULTILINE)
    assert react, "react not found in pnpm-lock.yaml"
    assert react_dom, "react-dom not found in pnpm-lock.yaml"
    assert react.group(1) == react_dom.group(1), (
        f"pnpm-lock resolves react@{react.group(1)} but react-dom@{react_dom.group(1)} "
        "— they must be identical (React #527)"
    )
