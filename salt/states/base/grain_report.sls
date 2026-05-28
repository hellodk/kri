# salt/states/base/grain_report.sls
# Reports current grain data to the Fleet Platform ingest API.
# Apply manually or via reactor on minion start:
#   salt '*' state.apply base.grain_report

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}

{% if ingest_url %}

report_grains_to_fleet_platform:
  cmd.run:
    - name: |
        python3 - <<'PYEOF'
        import subprocess, json, urllib.request
        raw = subprocess.check_output(
            ["/opt/salt/salt-call", "--local", "grains.items", "--out=json"],
            text=True
        )
        grains = json.loads(raw)["local"]
        payload = json.dumps({"minion_id": grains.get("id"), "grains": grains}).encode()
        req = urllib.request.Request(
            {{ (ingest_url ~ "/grains") | tojson }},
            data=payload,
            headers={"Content-Type": "application/json", "X-Node-Token": {{ node_token | tojson }}},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        print(resp.read().decode())
        PYEOF

{% endif %}
