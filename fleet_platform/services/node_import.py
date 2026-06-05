"""Bulk node import — parsers and validation (#360)."""

import csv
import io
import ipaddress
import re

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-_.]{0,253}[a-zA-Z0-9])?$")


def parse_paste(text: str) -> list[dict]:
    """Each line: 'ip' OR 'hostname,ip' OR 'minion_id,hostname,ip'. Skips blank/# lines."""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 1:
            ip = parts[0]
            rows.append({"minion_id": ip, "hostname": ip, "ip": ip})
        elif len(parts) == 2:
            host, ip = parts
            rows.append({"minion_id": host, "hostname": host, "ip": ip})
        else:
            rows.append({"minion_id": parts[0], "hostname": parts[1], "ip": parts[2]})
    return rows


def parse_csv(content: str, mapping: dict | None = None) -> list[dict]:
    """Parse CSV content into a list of row dicts.

    mapping: optional dict mapping canonical keys to CSV column names.
    Canonical keys: minion_id, hostname, ip, group, ssh_user.
    """
    mapping = mapping or {}
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for r in reader:

        def get(key: str, *alts: str) -> str:
            col = mapping.get(key)
            if col and col in r and r[col]:
                return r[col].strip()
            for k in (key, *alts):
                if k in r and r[k]:
                    return r[k].strip()
            return ""

        ip = get("ip", "ip_address", "address")
        host = get("hostname", "host", "name") or ip
        mid = get("minion_id", "minion", "id") or host
        if ip or host:
            rows.append(
                {
                    "minion_id": mid,
                    "hostname": host,
                    "ip": ip,
                    "group": get("group"),
                    "ssh_user": get("ssh_user", "ssh_username", "user"),
                }
            )
    return rows


def validate_row(row: dict, existing_minions: set, existing_ips: set) -> dict:
    """Validate a single row dict.

    Returns the row with 'status' and 'reason' keys added/updated.
    Status values: 'new', 'duplicate', 'invalid'.
    """
    mid = (row.get("minion_id") or "").strip()
    ip = (row.get("ip") or "").strip()
    host = (row.get("hostname") or "").strip()
    out = {**row, "minion_id": mid, "hostname": host, "ip": ip}

    if not mid:
        return {**out, "status": "invalid", "reason": "missing minion_id"}

    if ip:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return {**out, "status": "invalid", "reason": f"invalid IP: {ip}"}

    if host and not _HOSTNAME_RE.match(host):
        return {**out, "status": "invalid", "reason": f"invalid hostname: {host}"}

    if mid in existing_minions:
        return {**out, "status": "duplicate", "reason": "minion_id already exists"}

    if ip and ip in existing_ips:
        return {**out, "status": "duplicate", "reason": "IP already exists"}

    return {**out, "status": "new", "reason": ""}


def dedup_rows(rows: list[dict]) -> list[dict]:
    """Mark rows that duplicate an EARLIER 'new' row in the same batch as duplicate."""
    seen_mid: set[str] = set()
    seen_ip: set[str] = set()
    out: list[dict] = []

    for r in rows:
        mid = r.get("minion_id", "")
        ip = r.get("ip", "")
        if r.get("status") == "new" and (mid in seen_mid or (ip and ip in seen_ip)):
            out.append({**r, "status": "duplicate", "reason": "duplicate within import batch"})
        else:
            if r.get("status") == "new":
                seen_mid.add(mid)
                if ip:
                    seen_ip.add(ip)
            out.append(r)

    return out
