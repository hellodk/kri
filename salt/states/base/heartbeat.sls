# salt/states/base/heartbeat.sls
# Installs a salt minion schedule that runs grain_report every 5 minutes.
# Apply once during bootstrap or manually:
#   salt '*' state.apply base.heartbeat
#
# This gives kri a heartbeat so nodes stay "online" without manual triggers.

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}

{% if ingest_url %}

kri_heartbeat_script:
  file.managed:
    - name: /usr/local/bin/kri_heartbeat.py
    - mode: "0755"
    - contents: |
        #!/opt/salt/bin/python3.10
        """Send grains to kri ingest API — run by salt minion schedule every 5 min."""
        import subprocess, json, urllib.request, sys

        try:
            raw = subprocess.check_output(
                ["/opt/salt/salt-call", "--local", "grains.items", "--out=json"],
                text=True, timeout=30,
            )
            grains = json.loads(raw)["local"]
        except Exception as exc:
            print(f"[kri_heartbeat] grain collection failed: {exc}", file=sys.stderr)
            sys.exit(1)

        payload = json.dumps({"minion_id": grains.get("id"), "grains": grains}).encode()
        req = urllib.request.Request(
            {{ (ingest_url ~ "/grains") | tojson }},
            data=payload,
            headers={"Content-Type": "application/json", "X-Node-Token": {{ node_token | tojson }}},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            print(resp.read().decode())
        except Exception as exc:
            print(f"[kri_heartbeat] ingest failed: {exc}", file=sys.stderr)
            sys.exit(1)

kri_heartbeat_schedule:
  schedule.present:
    - name: kri_heartbeat
    - function: cmd.run
    - job_kwargs:
        cmd: /opt/salt/bin/python3.10 /usr/local/bin/kri_heartbeat.py
    - minutes: 5
    - enabled: True
    - require:
      - file: kri_heartbeat_script

{% endif %}
