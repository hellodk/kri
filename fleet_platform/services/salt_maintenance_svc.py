# fleet_platform/services/salt_maintenance_svc.py
"""Salt-based health metric collection for Mac Mini fleet nodes.

All parse_* functions are pure (no subprocess, no I/O) — easy to unit test.
collect_all_metrics() executes the actual Salt commands via docker exec.

Requires sudo access for powermetrics:
    salt ALL=(ALL) NOPASSWD: /usr/bin/powermetrics
"""
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_SALT_CONTAINER = os.environ.get("SALT_MASTER_CONTAINER", "deploy-salt-master-1")


# ── subprocess helper ─────────────────────────────────────────────────────────

def _run_salt(
    function: str,
    target: str,
    args: list[str] | None = None,
    timeout: int = 60,
) -> dict:
    """Run a Salt command via docker exec and return the parsed JSON output.

    Returns an empty dict on timeout, non-zero exit, or JSON parse failure.
    """
    cmd = ["docker", "exec", _SALT_CONTAINER, "salt", "-L", target,
           function, "--no-color", "--out=json"]
    if args:
        cmd += args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            logger.warning("_run_salt %s returned %d: %s", function, proc.returncode, proc.stderr[:200])
            return {}
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        logger.error("_run_salt %s timed out after %ds", function, timeout)
        return {}
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("_run_salt %s failed: %s", function, exc)
        return {}


# ── parsers ───────────────────────────────────────────────────────────────────

def parse_disk_usage(salt_out: dict, minion_id: str) -> dict:
    """Parse disk.usage Salt module output for one minion.

    Returns keys: disk_root_used_gb, disk_root_total_gb, disk_root_pct
    """
    node_data = salt_out.get(minion_id, {})
    root = node_data.get("/", {})
    if not root:
        return {"disk_root_used_gb": None, "disk_root_total_gb": None, "disk_root_pct": None}
    total_gb = root.get("1K-blocks", 0) / (1024 * 1024)
    used_gb = root.get("used", 0) / (1024 * 1024)
    pct_str = root.get("use%", "").strip().rstrip("%").strip()
    try:
        pct = int(pct_str)
    except ValueError:
        pct = None
    return {
        "disk_root_used_gb": round(used_gb, 2),
        "disk_root_total_gb": round(total_gb, 2),
        "disk_root_pct": pct,
    }


def parse_inode_usage(salt_out: dict, minion_id: str) -> dict:
    """Parse disk.inodeusage Salt module output. Returns disk_root_inodes_pct."""
    node_data = salt_out.get(minion_id, {})
    root = node_data.get("/", {})
    pct_str = root.get("use%", "").strip().rstrip("%").strip()
    try:
        return {"disk_root_inodes_pct": int(pct_str)}
    except ValueError:
        return {"disk_root_inodes_pct": None}


def parse_loadavg(salt_out: dict, minion_id: str) -> dict:
    """Parse status.loadavg Salt module output.

    Returns keys: cpu_load_1m, cpu_load_5m, cpu_load_15m
    """
    node_data = salt_out.get(minion_id, {})
    return {
        "cpu_load_1m": node_data.get("1-min"),
        "cpu_load_5m": node_data.get("5-min"),
        "cpu_load_15m": node_data.get("15-min"),
    }


def parse_vm_stat(vm_stat_text: str, total_bytes: int) -> dict:
    """Parse macOS vm_stat output.

    vm_stat_text: raw text from cmd.run "vm_stat"
    total_bytes: integer from cmd.run "sysctl -n hw.memsize"

    Returns keys: mem_total_gb, mem_available_gb, mem_used_pct
    """
    page_size = 16384  # standard macOS page size (16 KB)
    pages: dict[str, int] = {}
    for line in vm_stat_text.splitlines():
        for key in ("Pages free", "Pages speculative"):
            if line.strip().startswith(key):
                try:
                    pages[key] = int(line.split()[-1].rstrip("."))
                except (ValueError, IndexError):
                    pass

    if total_bytes <= 0:
        return {"mem_total_gb": None, "mem_available_gb": None, "mem_used_pct": 0}

    free_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
    free_bytes = free_pages * page_size
    total_gb = total_bytes / (1024 ** 3)
    free_gb = free_bytes / (1024 ** 3)
    used_gb = total_gb - free_gb
    used_pct = int((used_gb / total_gb) * 100) if total_gb > 0 else 0
    return {
        "mem_total_gb": round(total_gb, 2),
        "mem_available_gb": round(free_gb, 2),
        "mem_used_pct": min(used_pct, 100),
    }


def parse_uptime_seconds(uptime_text: str) -> int | None:
    """Parse macOS uptime output into total seconds.

    Examples:
        " 3:45  up 2 days, 18:23, 2 users, ..."  → 239_580
        " 3:45  up 47 mins, 1 user, ..."          → 2_820
    """
    if not uptime_text:
        return None
    days = 0
    m = re.search(r"up\s+(\d+)\s+day", uptime_text)
    if m:
        days = int(m.group(1))
    m2 = re.search(r"up\s+(?:\d+\s+days?,\s*)?(\d+):(\d+)", uptime_text)
    if m2:
        return days * 86400 + int(m2.group(1)) * 3600 + int(m2.group(2)) * 60
    m3 = re.search(r"up\s+(\d+)\s+min", uptime_text)
    if m3:
        return days * 86400 + int(m3.group(1)) * 60
    return None


def parse_gpu_info(raw_json: str) -> dict:
    """Parse system_profiler SPDisplaysDataType -json output.

    Returns keys: gpu_name, gpu_vram_mb
    """
    try:
        data = json.loads(raw_json)
        displays = data.get("SPDisplaysDataType", [])
        if not displays:
            return {"gpu_name": None, "gpu_vram_mb": None}
        gpu = displays[0]
        name = gpu.get("sppci_model") or gpu.get("_name")
        vram_str = gpu.get("spdisplays_vram") or gpu.get("spdisplays_vram_shared", "")
        vram_mb = None
        if vram_str:
            parts = vram_str.split()
            if len(parts) >= 2:
                try:
                    val = int(parts[0])
                    unit = parts[1].upper()
                    vram_mb = val * 1024 if unit == "GB" else val
                except ValueError:
                    pass
        return {"gpu_name": name, "gpu_vram_mb": vram_mb}
    except Exception:
        return {"gpu_name": None, "gpu_vram_mb": None}


def parse_powermetrics(raw_json: str) -> dict:
    """Parse powermetrics --output-format json output.

    Handles both Apple Silicon and Intel field layouts.
    Returns keys: cpu_power_mw, gpu_power_mw, thermal_pressure
    """
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return {"cpu_power_mw": None, "gpu_power_mw": None, "thermal_pressure": None}

    cpu_power = None
    gpu_power = None

    # Apple Silicon: processor.packages[0].package_mw
    if "processor" in data:
        pkgs = data["processor"].get("packages", [])
        if pkgs:
            cpu_power = pkgs[0].get("package_mw")
    # Intel: cpu_power.package_mw
    elif "cpu_power" in data:
        cpu_power = data["cpu_power"].get("package_mw")

    # Apple Silicon: gpu.package_mw  |  Intel: gpu_power.gpu_mw
    if "gpu" in data:
        v = data["gpu"].get("package_mw")
        gpu_power = v if v is not None else data["gpu"].get("gpu_mw")
    elif "gpu_power" in data:
        gpu_power = data["gpu_power"].get("gpu_mw")

    thermal = data.get("thermal_pressure") or data.get("thermalPressure")

    return {
        "cpu_power_mw": int(cpu_power) if cpu_power is not None else None,
        "gpu_power_mw": int(gpu_power) if gpu_power is not None else None,
        "thermal_pressure": str(thermal) if thermal else None,
    }


# ── collection orchestrator ───────────────────────────────────────────────────

def collect_all_metrics(minion_ids: list[str]) -> dict[str, dict]:
    """Run all health Salt commands against minion_ids and return parsed metrics per minion.

    Called from the collect_fleet_health Celery task.
    Each command targets all minions in one Salt call for efficiency.
    powermetrics may return None fields if sudo is not configured.
    """
    if not minion_ids:
        return {}

    target = ",".join(minion_ids)
    results: dict[str, dict] = {mid: {"error": None} for mid in minion_ids}

    def _apply(parse_fn, salt_out: dict) -> None:
        for mid in minion_ids:
            try:
                results[mid].update(parse_fn(salt_out, mid))
            except Exception as exc:
                logger.warning("parse error for %s in %s: %s", mid, parse_fn.__name__, exc)

    _apply(parse_disk_usage, _run_salt("disk.usage", target))
    _apply(parse_inode_usage, _run_salt("disk.inodeusage", target))
    _apply(parse_loadavg, _run_salt("status.loadavg", target))

    vmstat_out = _run_salt("cmd.run", target, args=["vm_stat"])
    hwmem_out = _run_salt("cmd.run", target, args=["sysctl -n hw.memsize"])
    for mid in minion_ids:
        try:
            total_bytes = int(hwmem_out.get(mid, "0").strip())
        except (ValueError, AttributeError):
            total_bytes = 0
        results[mid].update(parse_vm_stat(vmstat_out.get(mid, ""), total_bytes))

    uptime_out = _run_salt("cmd.run", target, args=["uptime"])
    for mid in minion_ids:
        results[mid]["uptime_seconds"] = parse_uptime_seconds(uptime_out.get(mid, ""))

    gpu_out = _run_salt("cmd.run", target, args=["system_profiler SPDisplaysDataType -json"])
    for mid in minion_ids:
        results[mid].update(parse_gpu_info(gpu_out.get(mid, "")))

    pm_out = _run_salt(
        "cmd.run", target,
        args=["sudo powermetrics -n 1 -i 500 --samplers cpu_power,gpu_power,thermal --output-format json 2>/dev/null"],
        timeout=30,
    )
    for mid in minion_ids:
        results[mid].update(parse_powermetrics(pm_out.get(mid, "")))

    return results
