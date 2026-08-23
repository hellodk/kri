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
# Token handling (#1047 hardening): the node token is NEVER baked into the
# world-readable script or config. It is written to /etc/kri/node_token
# (directory 0700, file 0600, root-owned) and the script reads it at runtime.
#
# Cross-platform (#673/#1047): file group is the OS-appropriate root group
# (wheel on macOS, root on Linux — Linux has no wheel group by default), and
# the minion reload uses launchctl on macOS vs systemctl on Linux (mirrors
# process_report_schedule.sls).
#
# Apply once during bootstrap (playbooks/roles/kri_enroll), then idempotent on
# every salt highstate:
#   salt '*' state.apply base.heartbeat

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}
{% set is_linux = grains['os_family'] in ['Debian', 'RedHat', 'Suse', 'Arch', 'Gentoo', 'Alpine'] %}

{% if ingest_url %}

# Layer 0: runtime token store — root-only directory + 0600 token file so the
# heartbeat script can authenticate without secrets in readable scripts/configs.
kri_etc_kri_dir:
  file.directory:
    - name: /etc/kri
    - user: root
    - group: {% if is_linux %}root{% else %}wheel{% endif %}
    - mode: "0700"
    - makedirs: True

kri_node_token:
  file.managed:
    - name: /etc/kri/node_token
    - user: root
    - group: {% if is_linux %}root{% else %}wheel{% endif %}
    - mode: "0600"
    - contents: {{ node_token | tojson }}
    - require:
      - file: kri_etc_kri_dir

# Layer 1: persistent schedule config in minion.d — survives cache clears
kri_heartbeat_minion_conf:
  file.managed:
    - name: /etc/salt/minion.d/kri-heartbeat.conf
    - user: root
    - group: {% if is_linux %}root{% else %}wheel{% endif %}
    - mode: "0644"
    - contents: |
        # kri heartbeat schedule — written by salt/states/base/heartbeat.sls
        # DO NOT EDIT: managed by kri. Remove to disable.
        schedule:
          kri_heartbeat:
            function: cmd.run
            args:
              - /opt/salt/bin/python3 /usr/local/bin/kri_heartbeat.py
            minutes: 5
            enabled: True
            run_on_start: True

# Layer 2: heartbeat script — reads the token from /etc/kri/node_token at runtime
kri_heartbeat_script:
  file.managed:
    - name: /usr/local/bin/kri_heartbeat.py
    - user: root
    - group: {% if is_linux %}root{% else %}wheel{% endif %}
    - mode: "0750"
    - contents: |
        #!/opt/salt/bin/python3
        """Send grains to kri ingest API — run by salt minion schedule every 5 min."""
        import subprocess, json, urllib.request, sys

        try:
            node_token = open('/etc/kri/node_token').read().strip()
        except OSError as exc:
            print(f"[kri_heartbeat] cannot read /etc/kri/node_token: {exc}", file=sys.stderr)
            sys.exit(1)

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
            headers={"Content-Type": "application/json", "X-Node-Token": node_token},
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
      - file: kri_node_token

# Restart salt-minion to pick up the new schedule from minion.d.
# H2-fix (audit): the restart is detached with nohup so it outlives the salt state
# that triggers it. Without detach, 'launchctl stop' kills the minion mid-state-run
# (the state is executing INSIDE the process being killed), producing non-deterministic
# results ranging from partial-apply to the minion not restarting at all.
# Branched like process_report_schedule.sls: systemctl on Linux, launchctl elsewhere.
{% if is_linux %}
kri_heartbeat_reload_minion:
  cmd.run:
    - name: >
        nohup sh -c
        'sleep 3 &&
        systemctl restart salt-minion'
        >/dev/null 2>&1 &
    - onchanges:
        - file: kri_heartbeat_minion_conf
{% else %}
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

{% endif %}
