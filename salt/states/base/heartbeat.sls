# salt/states/base/heartbeat.sls
# Installs the kri heartbeat — two complementary layers:
#
# Layer 1 (config file): writes /etc/salt/minion.d/kri-heartbeat.conf
#   This is a persistent static config file in the minion's config directory.
#   It survives: minion restarts, cache clears, salt upgrades, system reboots.
#   The schedule entry is read directly from the config, not from volatile cache.
#
# Layer 2 (script): writes /usr/local/bin/kri_heartbeat.py
#   The script that posts grains to kri. Called by the schedule every 5 minutes.
#
# Apply once during bootstrap, then idempotent on every salt highstate:
#   salt '*' state.apply base.heartbeat

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}

{% if ingest_url %}

# Layer 1: persistent schedule config in minion.d — survives cache clears
kri_heartbeat_minion_conf:
  file.managed:
    - name: /etc/salt/minion.d/kri-heartbeat.conf
    - user: root
    - group: wheel
    - mode: "0644"
    - contents: |
        # kri heartbeat schedule — written by salt/states/base/heartbeat.sls
        # DO NOT EDIT: managed by kri. Remove to disable.
        schedule:
          kri_heartbeat:
            function: cmd.run
            job_kwargs:
              cmd: /opt/salt/bin/python3.10 /usr/local/bin/kri_heartbeat.py
            minutes: 5
            enabled: True
            run_on_start: True

# Layer 2: heartbeat script
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
    - require:
      - file: kri_heartbeat_minion_conf

# Restart salt-minion to pick up the new schedule from minion.d.
# H2-fix (audit): the restart is detached with nohup so it outlives the salt state
# that triggers it. Without detach, 'launchctl stop' kills the minion mid-state-run
# (the state is executing INSIDE the process being killed), producing non-deterministic
# results ranging from partial-apply to the minion not restarting at all.
kri_heartbeat_reload_minion:
  cmd.run:
    - name: >
        nohup sh -c
        'sleep 3 &&
        launchctl stop com.saltstack.salt.minion &&
        sleep 2 &&
        launchctl start com.saltstack.salt.minion'
        >/dev/null 2>&1 &
    - onchanges:
      - file: kri_heartbeat_minion_conf

{% endif %}
