"""Custom grain: list installed macOS configuration profile UUIDs."""
import subprocess


def mobileconfig_installed():
    """Return dict with key 'mobileconfig_installed': list of UUIDs."""
    try:
        result = subprocess.run(
            ["profiles", "list", "-output", "stdout-xml"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"mobileconfig_installed": []}
        import plistlib
        data = plistlib.loads(result.stdout.encode())
        uuids = [
            p.get("PayloadUUID", "")
            for p in data.get("_computerlevel", []) + data.get("_devicelevel", [])
            if p.get("PayloadUUID")
        ]
        return {"mobileconfig_installed": uuids}
    except Exception:
        return {"mobileconfig_installed": []}
