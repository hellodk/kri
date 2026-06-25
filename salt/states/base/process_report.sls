# salt/states/base/process_report.sls
# Deploys and runs the kri process telemetry collector on each minion.
#
# What it does:
#   1. Ensures psutil is installed for the system python3 (idempotent guard).
#   2. Pushes the standalone collector script to /opt/kri/process_collector.py.
#   3. Runs the collector, which posts per-process stats to:
#        POST {{ ingest_url }}/process_stats  (X-Node-Token: <node_token>)
#      The collector appends /process_stats to the INGEST_URL env var itself.
#
# The collector caps output at 200 processes (top by RSS); the ingest endpoint
# accepts up to 250.
#
# Cross-platform (#673): on Linux psutil comes from the distro package manager
# (PEP 668 / externally-managed-environment safe, no runtime pip on a recurring
# schedule); on macOS it stays an idempotent user-pip install guarded by an
# import check so it never runs once psutil is importable.
#
# Apply manually or via schedule (see process_report_schedule.sls):
#   salt '*' state.apply base.process_report

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}
{% set is_linux = grains['os_family'] in ['Debian', 'RedHat', 'Suse', 'Arch', 'Gentoo', 'Alpine'] %}

{% if ingest_url %}

# Step 1 — ensure psutil is available for system python3
{% if is_linux %}
# Linux: use the distro package (python3-psutil) so we never run pip on the
# 30s schedule — avoids PEP 668 breakage and the supply-chain risk of pulling
# from PyPI on every tick.
kri_psutil_install:
  pkg.installed:
    - name: python3-psutil
    - unless: python3 -c "import psutil"
{% else %}
# macOS (and any non-Linux): idempotent user-pip install. The unless guard means
# pip only ever runs when psutil is not importable, so the recurring schedule
# does not reinstall on every tick.
kri_psutil_install:
  cmd.run:
    - name: python3 -m pip install --quiet --user psutil
    - unless: python3 -c "import psutil"
{% endif %}

# Step 2 — push the collector script from the Salt file server
kri_process_collector_script:
  file.managed:
    - name: /opt/kri/process_collector.py
    - source: salt://base/files/process_collector.py
    - makedirs: True
    - mode: "0755"

# Step 3 — run the collector
# The collector POSTs to {{ (ingest_url ~ "/process_stats") }}
# INGEST_URL is the base URL; process_collector.py appends /process_stats internally.
kri_process_report_run:
  cmd.run:
    - name: python3 /opt/kri/process_collector.py
    - env:
        - INGEST_URL: {{ ingest_url | tojson }}
        - NODE_TOKEN: {{ node_token | tojson }}
        - MINION_ID: "{{ grains['id'] }}"
    - require:
{% if is_linux %}
        - pkg: kri_psutil_install
{% else %}
        - cmd: kri_psutil_install
{% endif %}
        - file: kri_process_collector_script

{% endif %}
