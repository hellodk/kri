#!/usr/bin/env python3
"""Seed default users into the Docker kri database."""
import bcrypt
import subprocess
import tempfile
import os

USERS = [
    ("admin@fleet.local", "changeme", "admin"),
    ("viewer@fleet.local", "changeme", "viewer"),
    ("admin@admin.com", "changeme", "admin"),
]

rows = []
for email, pw, role in USERS:
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()
    rows.append((email, h, role))

lines = ["INSERT INTO users (id,email,password_hash,role,is_active,created_at,updated_at) VALUES"]
vals = []
for email, h, role in rows:
    vals.append(f"  (gen_random_uuid(), '{email}', '{h}', '{role}', true, now(), now())")
lines.append(",\n".join(vals))
lines.append("ON CONFLICT (email) DO UPDATE SET password_hash=EXCLUDED.password_hash, role=EXCLUDED.role;")
lines.append("SELECT email, role FROM users ORDER BY email;")
sql = "\n".join(lines)

with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
    f.write(sql)
    tmpfile = f.name

try:
    subprocess.run(["docker", "cp", tmpfile, "deploy-db-1:/tmp/seed_users.sql"], check=True)
    result = subprocess.run(
        ["docker", "exec", "deploy-db-1", "psql", "-U", "fleet", "-d", "fleet_demo", "-f", "/tmp/seed_users.sql"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
finally:
    os.unlink(tmpfile)
