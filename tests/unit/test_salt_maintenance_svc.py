# tests/unit/test_salt_maintenance_svc.py
"""Unit tests for salt_maintenance_svc parsing functions. No subprocess, no network."""


def test_parse_disk_usage_extracts_root_metrics():
    from fleet_platform.services.salt_maintenance_svc import parse_disk_usage

    salt_out = {
        "mac-mini-01": {
            "/": {"1K-blocks": 245094400, "used": 100000000, "available": 145094400, "use%": "41%"},
            "/System/Volumes/Data": {"1K-blocks": 245094400, "used": 50000000, "available": 195094400, "use%": "21%"},
        }
    }
    result = parse_disk_usage(salt_out, "mac-mini-01")
    # 245094400 / (1024*1024) ≈ 233.7 GB; 100000000 / (1024*1024) ≈ 95.37 GB
    expected_total_gb = round(245094400 / (1024 * 1024), 2)
    expected_used_gb = round(100000000 / (1024 * 1024), 2)
    assert result["disk_root_pct"] == 41
    assert result["disk_root_total_gb"] == expected_total_gb
    assert result["disk_root_used_gb"] == expected_used_gb


def test_parse_disk_usage_returns_none_for_missing_minion():
    from fleet_platform.services.salt_maintenance_svc import parse_disk_usage

    result = parse_disk_usage({}, "mac-mini-99")
    assert result["disk_root_pct"] is None
    assert result["disk_root_used_gb"] is None


def test_parse_inode_usage_extracts_root_pct():
    from fleet_platform.services.salt_maintenance_svc import parse_inode_usage

    salt_out = {
        "mac-mini-01": {
            "/": {"inodes": 4882452480, "used": 500000, "free": 4881952480, "use%": "1%"},
        }
    }
    result = parse_inode_usage(salt_out, "mac-mini-01")
    assert result["disk_root_inodes_pct"] == 1


def test_parse_loadavg_extracts_three_values():
    from fleet_platform.services.salt_maintenance_svc import parse_loadavg

    salt_out = {"mac-mini-01": {"1-min": 1.23, "5-min": 0.98, "15-min": 0.75}}
    result = parse_loadavg(salt_out, "mac-mini-01")
    assert result["cpu_load_1m"] == 1.23
    assert result["cpu_load_5m"] == 0.98
    assert result["cpu_load_15m"] == 0.75


def test_parse_loadavg_missing_minion_returns_none():
    from fleet_platform.services.salt_maintenance_svc import parse_loadavg

    result = parse_loadavg({}, "mac-mini-99")
    assert result["cpu_load_1m"] is None


def test_parse_vm_stat_computes_used_pct():
    from fleet_platform.services.salt_maintenance_svc import parse_vm_stat

    vm_stat_text = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                          4028.
Pages active:                       50000.
Pages inactive:                     20000.
Pages speculative:                    100.
Pages throttled:                        0.
Pages wired down:                   30000.
"""
    total_bytes = 8 * 1024**3  # 8 GB
    result = parse_vm_stat(vm_stat_text, total_bytes)

    free_pages = 4028 + 100  # Pages free + Pages speculative
    free_bytes = free_pages * 16384
    total_gb = total_bytes / (1024**3)
    free_gb = free_bytes / (1024**3)
    used_gb = total_gb - free_gb
    expected_pct = int((used_gb / total_gb) * 100)

    assert result["mem_total_gb"] == 8.0
    assert result["mem_used_pct"] == expected_pct
    assert round(result["mem_available_gb"], 2) == round(free_gb, 2)


def test_parse_vm_stat_zero_total_bytes_safe():
    from fleet_platform.services.salt_maintenance_svc import parse_vm_stat

    result = parse_vm_stat("", 0)
    assert result["mem_used_pct"] == 0


def test_parse_uptime_seconds_days_and_hours():
    from fleet_platform.services.salt_maintenance_svc import parse_uptime_seconds

    text = " 3:45  up 2 days, 18:23, 2 users, load averages: 1.23 0.98 0.75"
    seconds = parse_uptime_seconds(text)
    assert seconds == 2 * 86400 + 18 * 3600 + 23 * 60


def test_parse_uptime_seconds_minutes_only():
    from fleet_platform.services.salt_maintenance_svc import parse_uptime_seconds

    text = " 3:45  up 47 mins, 1 user, load averages: 0.50 0.30 0.20"
    seconds = parse_uptime_seconds(text)
    assert seconds == 47 * 60


def test_parse_uptime_seconds_invalid_returns_none():
    from fleet_platform.services.salt_maintenance_svc import parse_uptime_seconds

    assert parse_uptime_seconds("") is None
    assert parse_uptime_seconds("garbage text") is None


def test_parse_gpu_info_extracts_name_and_vram():
    from fleet_platform.services.salt_maintenance_svc import parse_gpu_info

    raw_json = '{"SPDisplaysDataType": [{"sppci_model": "Apple M2 GPU", "spdisplays_vram": "8 GB"}]}'
    result = parse_gpu_info(raw_json)
    assert result["gpu_name"] == "Apple M2 GPU"
    assert result["gpu_vram_mb"] == 8192


def test_parse_gpu_info_mb_vram():
    from fleet_platform.services.salt_maintenance_svc import parse_gpu_info

    raw_json = '{"SPDisplaysDataType": [{"sppci_model": "Intel Iris Plus", "spdisplays_vram": "1536 MB"}]}'
    result = parse_gpu_info(raw_json)
    assert result["gpu_vram_mb"] == 1536


def test_parse_gpu_info_invalid_json_returns_none():
    from fleet_platform.services.salt_maintenance_svc import parse_gpu_info

    result = parse_gpu_info("not json")
    assert result["gpu_name"] is None
    assert result["gpu_vram_mb"] is None


def test_parse_powermetrics_apple_silicon():
    import json

    from fleet_platform.services.salt_maintenance_svc import parse_powermetrics

    data = {
        "processor": {"packages": [{"package_mw": 5000}]},
        "gpu": {"package_mw": 1500},
        "thermal_pressure": "Nominal",
    }
    result = parse_powermetrics(json.dumps(data))
    assert result["cpu_power_mw"] == 5000
    assert result["gpu_power_mw"] == 1500
    assert result["thermal_pressure"] == "Nominal"


def test_parse_powermetrics_intel_format():
    import json

    from fleet_platform.services.salt_maintenance_svc import parse_powermetrics

    data = {
        "cpu_power": {"package_mw": 8000},
        "gpu_power": {"gpu_mw": 2000},
        "thermal_pressure": "Light",
    }
    result = parse_powermetrics(json.dumps(data))
    assert result["cpu_power_mw"] == 8000
    assert result["gpu_power_mw"] == 2000
    assert result["thermal_pressure"] == "Light"


def test_parse_powermetrics_bad_json_returns_none_fields():
    from fleet_platform.services.salt_maintenance_svc import parse_powermetrics

    result = parse_powermetrics("sudo: powermetrics: command not found")
    assert result["cpu_power_mw"] is None
    assert result["gpu_power_mw"] is None
    assert result["thermal_pressure"] is None
