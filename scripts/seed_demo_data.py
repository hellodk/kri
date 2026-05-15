"""
Seed demo data for Fleet Platform development/demo.
Run: source .venv/bin/activate && python scripts/seed_demo_data.py
"""
import uuid
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fleet_platform.core.config import settings
from fleet_platform.core.auth import hash_password
from fleet_platform.models import Base
from fleet_platform.models.node import Node
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.group import Group, GroupMember
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.sbom import SBOMScan, SBOMComponent
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.models.audit import AuditEvent

# Use sync engine for seeding
engine = create_engine(settings.database_url.replace("+psycopg", ""), echo=False)

HOSTNAMES = [
    ("mac-mini-01", "10.0.1.11", "macOS 14.4.1", "Sequoia 23E224", "Mac mini (Late 2023)", 12, 32.0, 512.0),
    ("mac-mini-02", "10.0.1.12", "macOS 14.4.1", "Sequoia 23E224", "Mac mini (Late 2023)", 12, 32.0, 512.0),
    ("mac-mini-03", "10.0.1.13", "macOS 14.3.0", "Sonoma 23D56",   "Mac mini (2022)",      8,  16.0, 256.0),
    ("mac-mini-04", "10.0.1.14", "macOS 14.4.1", "Sequoia 23E224", "Mac mini (Late 2023)", 12, 64.0, 1024.0),
    ("mac-mini-05", "10.0.1.15", "macOS 13.6.4", "Ventura 22G513", "Mac mini (2020)",      8,  16.0, 256.0),
    ("builder-01",  "10.0.2.21", "macOS 14.4.1", "Sequoia 23E224", "Mac Pro (2023)",       24, 192.0, 4096.0),
    ("builder-02",  "10.0.2.22", "macOS 14.4.0", "Sequoia 23E214", "Mac Pro (2023)",       24, 192.0, 4096.0),
    ("lab-01",      "10.0.3.31", "macOS 14.2.1", "Sonoma 23C71",   "MacBook Pro 16-inch",  12, 36.0,  512.0),
    ("lab-02",      "10.0.3.32", "macOS 14.4.1", "Sequoia 23E224", "MacBook Pro 14-inch",  12, 18.0,  512.0),
    ("qa-01",       "10.0.4.41", "macOS 14.4.1", "Sequoia 23E224", "Mac mini (Late 2023)", 12, 32.0,  512.0),
]

STATUSES = ["online", "online", "online", "online", "online", "online", "stale", "stale", "offline", "online"]

NODE_TAGS = [
    [("env", "prod"), ("role", "worker")],
    [("env", "prod"), ("role", "worker")],
    [("env", "prod"), ("role", "worker")],
    [("env", "prod"), ("role", "worker"), ("tier", "critical")],
    [("env", "prod"), ("role", "worker")],
    [("env", "prod"), ("role", "builder"), ("ci", "true")],
    [("env", "prod"), ("role", "builder"), ("ci", "true")],
    [("env", "dev"), ("role", "lab")],
    [("env", "dev"), ("role", "lab")],
    [("env", "staging"), ("role", "qa")],
]

DRIFT_SCORES = [3, 8, 42, 0, 67, 15, 91, 5, 22, 0]

PACKAGES = [
    ("openssl", "3.0.2", "pkg:brew/openssl@3.0.2", "library", ["OpenSSL"]),
    ("git", "2.42.0", "pkg:brew/git@2.42.0", "application", []),
    ("python", "3.13.0", "pkg:brew/python@3.13.0", "application", ["PSF-2.0"]),
    ("curl", "8.5.0", "pkg:brew/curl@8.5.0", "application", ["MIT"]),
    ("node", "20.11.0", "pkg:brew/node@20.11.0", "application", ["MIT"]),
    ("postgresql", "17.0", "pkg:brew/postgresql@17.0", "application", ["PostgreSQL"]),
    ("redis", "7.2.4", "pkg:brew/redis@7.2.4", "application", ["BSD-3-Clause"]),
    ("nginx", "1.25.3", "pkg:brew/nginx@1.25.3", "application", ["BSD-2-Clause"]),
    ("jq", "1.7.1", "pkg:brew/jq@1.7.1", "library", ["MIT"]),
    ("wget", "1.21.4", "pkg:brew/wget@1.21.4", "application", ["GPL-3.0"]),
    ("htop", "3.3.0", "pkg:brew/htop@3.3.0", "application", ["GPL-2.0"]),
    ("vim", "9.1.0", "pkg:brew/vim@9.1.0", "application", ["Vim"]),
    ("tmux", "3.4", "pkg:brew/tmux@3.4", "application", ["ISC"]),
    ("ripgrep", "14.1.0", "pkg:brew/ripgrep@14.1.0", "application", ["MIT"]),
    ("fd", "9.0.0", "pkg:brew/fd@9.0.0", "application", ["MIT"]),
]

JOB_TYPES = ["highstate", "state_apply", "grain_sync", "sbom_scan", "pkg.install"]


def random_time(days_ago_max=30, days_ago_min=0):
    delta = random.uniform(days_ago_min * 86400, days_ago_max * 86400)
    return datetime.now(UTC) - timedelta(seconds=delta)


def seed():
    with Session(engine) as db:
        # Clear existing demo data (keep users)
        print("Clearing existing data...")
        for table in ["audit_events", "execution_results", "execution_jobs",
                      "sbom_components", "sbom_scans", "drift_records",
                      "desired_state_baselines", "group_members", "groups",
                      "node_facts", "nodes"]:
            db.execute(text(f"DELETE FROM {table}"))
        db.commit()

        # --- Baselines ---
        print("Creating baselines...")
        baseline_global = DesiredStateBaseline(
            name="global",
            description="Global baseline for all production nodes",
            target_type="global",
            git_commit_sha="abc1234def5678",
            state_json={
                "packages": {
                    "required": [
                        {"name": "openssl", "min_version": "3.0.0"},
                        {"name": "git", "min_version": "2.40.0"},
                        {"name": "curl"},
                    ]
                },
                "services": {"required": ["sshd"]},
            },
            version=1,
        )
        baseline_builder = DesiredStateBaseline(
            name="builder",
            description="Builder nodes with CI toolchain",
            target_type="group",
            git_commit_sha="abc1234def5678",
            state_json={
                "packages": {
                    "required": [
                        {"name": "openssl", "min_version": "3.0.0"},
                        {"name": "git", "min_version": "2.40.0"},
                        {"name": "node", "min_version": "20.0.0"},
                        {"name": "python", "min_version": "3.12.0"},
                    ]
                }
            },
            version=1,
        )
        db.add_all([baseline_global, baseline_builder])
        db.flush()

        # --- Nodes ---
        print("Creating nodes...")
        nodes = []
        now = datetime.now(UTC)
        for i, (hostname, ip, os_ver, os_build, hw_model, cpu, ram, storage) in enumerate(HOSTNAMES):
            last_seen = now - timedelta(minutes=random.randint(1, 20)) if STATUSES[i] == "online" else \
                        now - timedelta(minutes=random.randint(20, 60)) if STATUSES[i] == "stale" else \
                        now - timedelta(hours=random.randint(2, 48))
            node = Node(
                id=uuid.uuid4(),
                minion_id=f"{hostname}.fleet.local",
                hostname=hostname,
                ip_address=ip,
                os_version=os_ver,
                os_build=os_build,
                hardware_model=hw_model,
                cpu_cores=cpu,
                ram_gb=ram,
                storage_gb=storage,
                status=STATUSES[i],
                drift_score=DRIFT_SCORES[i],
                node_token_hash=hash_password(f"token-{hostname}"),
                first_seen_at=now - timedelta(days=random.randint(30, 180)),
                last_seen_at=last_seen,
            )
            nodes.append(node)
            db.add(node)
        db.flush()

        # Tags (stored in JSON via node_facts, but tags table via separate model)
        # Tags are on the Node via the tags relationship — add them via direct insert
        for i, node in enumerate(nodes):
            for key, value in NODE_TAGS[i]:
                db.execute(text(
                    "INSERT INTO tags (node_id, key, value) VALUES (:node_id, :key, :value) "
                    "ON CONFLICT (node_id, key) DO UPDATE SET value = :value"
                ), {"node_id": str(node.id), "key": key, "value": value})

        # --- Groups ---
        print("Creating groups...")
        group_prod = Group(name="production", description="All production Mac Minis", type="dynamic",
                           predicate={"and": [{"key": "env", "value": "prod"}]})
        group_builders = Group(name="builders", description="CI builder nodes", type="static")
        group_dev = Group(name="dev-lab", description="Development lab machines", type="static")
        db.add_all([group_prod, group_builders, group_dev])
        db.flush()

        # Static group members
        for node in nodes[5:7]:  # builder-01, builder-02
            db.add(GroupMember(group_id=group_builders.id, node_id=node.id))
        for node in nodes[7:9]:  # lab-01, lab-02
            db.add(GroupMember(group_id=group_dev.id, node_id=node.id))
        db.flush()

        # --- Node Facts ---
        print("Creating node facts...")
        for node in nodes:
            grains = {
                "id": node.minion_id,
                "fqdn": node.hostname,
                "ipv4": [node.ip_address],
                "os": "MacOS",
                "osrelease": node.os_version,
                "osbuild": node.os_build,
                "productname": node.hardware_model,
                "num_cpus": node.cpu_cores,
                "mem_total": int(node.ram_gb * 1024),
                "cpu_model": "Apple M3 Pro",
                "serialnumber": f"C02{random.randint(10000,99999)}",
                "uptime_seconds": random.randint(3600, 86400 * 7),
                "pkg_list": [{"name": p[0], "version": p[1]} for p in random.sample(PACKAGES, 8)],
            }
            fact = NodeFact(
                node_id=node.id,
                grains=grains,
                reported_at=node.last_seen_at,
            )
            db.add(fact)

        # --- Drift Records ---
        print("Creating drift records...")
        for i, node in enumerate(nodes):
            score = DRIFT_SCORES[i]
            missing = []
            extra = []
            mismatches = []
            if score > 20:
                missing = [{"name": "openssl", "required_version": "3.0.0"}]
            if score > 50:
                extra = [{"name": "teamviewer", "installed_version": "15.0.0"}]
                mismatches = [{"name": "git", "expected": "2.42.0", "actual": "2.38.0"}]
            if score > 80:
                missing.append({"name": "curl", "required_version": None})

            severity = "clean" if score <= 5 else "low" if score <= 20 else \
                       "medium" if score <= 50 else "high" if score <= 80 else "critical"

            # Multiple historical records
            for days_ago in [0, 3, 7, 14, 21, 28]:
                hist_score = max(0, score + random.randint(-10, 10))
                hist_severity = "clean" if hist_score <= 5 else "low" if hist_score <= 20 else \
                                "medium" if hist_score <= 50 else "high" if hist_score <= 80 else "critical"
                record = DriftRecord(
                    node_id=node.id,
                    baseline_id=baseline_global.id,
                    computed_at=datetime.now(UTC) - timedelta(days=days_ago, hours=random.randint(0, 6)),
                    drift_score=hist_score if days_ago > 0 else score,
                    missing_packages=missing,
                    extra_packages=extra,
                    version_mismatches=mismatches,
                    service_drift=[],
                    config_drift=[],
                )
                db.add(record)

        # --- SBOM Scans ---
        print("Creating SBOM data...")
        for node in nodes:
            scan = SBOMScan(
                node_id=node.id,
                syft_version="1.3.0",
                format="cyclonedx",
                scanned_at=datetime.now(UTC) - timedelta(hours=random.randint(1, 24)),
                component_count=len(PACKAGES),
            )
            db.add(scan)
            db.flush()
            for name, version, purl, comp_type, licenses in PACKAGES:
                db.add(SBOMComponent(
                    scan_id=scan.id,
                    node_id=node.id,
                    name=name,
                    version=version,
                    purl=purl,
                    component_type=comp_type,
                    licenses=licenses,
                    cpes=[],
                ))

        # --- Execution Jobs ---
        print("Creating execution history...")
        for _ in range(20):
            node = random.choice(nodes)
            job_type = random.choice(JOB_TYPES)
            started = random_time(days_ago_max=7)
            completed = started + timedelta(seconds=random.randint(5, 120))
            status = random.choices(["completed", "completed", "completed", "failed"], k=1)[0]
            job = ExecutionJob(
                id=uuid.uuid4(),
                salt_jid=f"20260514{random.randint(100000,999999)}.{random.randint(100000,999999)}",
                type=job_type,
                target_type="node",
                target_id=node.id,
                triggered_by="admin@fleet.local",
                status=status,
                started_at=started,
                completed_at=completed,
                metadata={"args": []},
            )
            db.add(job)
            db.flush()
            result = ExecutionResult(
                job_id=job.id,
                node_id=node.id,
                status="success" if status == "completed" else "failure",
                exit_code=0 if status == "completed" else 1,
                stdout=f"[INFO] {job_type} completed successfully\n" if status == "completed" else "",
                stderr="" if status == "completed" else f"[ERROR] {job_type} failed: command not found\n",
                completed_at=completed,
            )
            db.add(result)

        db.commit()
        print("\n✓ Demo data seeded successfully!")
        print(f"  {len(nodes)} nodes ({sum(1 for s in STATUSES if s=='online')} online, "
              f"{sum(1 for s in STATUSES if s=='stale')} stale, "
              f"{sum(1 for s in STATUSES if s=='offline')} offline)")
        print(f"  3 groups, 2 baselines, {len(nodes)*6} drift records, "
              f"{len(nodes)} SBOM scans ({len(nodes)*len(PACKAGES)} components), 20 execution jobs")


if __name__ == "__main__":
    seed()
