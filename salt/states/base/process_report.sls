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
# Apply manually or via schedule (see process_report_schedule.sls):
#   salt '*' state.apply base.process_report

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}

{% if ingest_url %}

# Step 1 — ensure psutil is available for system python3
kri_psutil_install:
  cmd.run:
    - name: python3 -m pip install --quiet --user psutil
    - unless: python3 -c "import psutil"

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
        - cmd: kri_psutil_install
        - file: kri_process_collector_script

{% endif %}
