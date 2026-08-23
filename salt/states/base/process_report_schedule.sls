# salt/states/base/process_report_schedule.sls
# Installs a persistent Salt schedule entry that runs the kri process telemetry
# collector every 30 seconds on each minion.
#
# PREREQUISITE (#1047): base.process_report must be applied once BEFORE (or at
# least together with) this state — it installs psutil and pushes the collector
# script to /opt/kri/process_collector.py. This state is schedule-only: the
# collector is invoked directly instead of re-running the whole
# base.process_report state on every tick.
#
# Application point (same as base.heartbeat): applied during enrollment by
# playbooks/roles/kri_enroll/tasks/main.yml ("Apply kri heartbeat schedule"
# immediately followed by "Apply kri process-report schedule"), or manually:
#   salt '*' state.apply base.process_report && \
#     salt '*' state.apply base.process_report_schedule
#
# This writes a minion.d config file so the schedule survives cache clears
# and minion restarts (same pattern as heartbeat.sls).
#
# To disable: remove the file and restart the minion:
#   salt '*' file.remove /etc/salt/minion.d/kri-process-report.conf
#   salt '*' service.restart salt-minion
#
# Token handling (#1047 hardening): INGEST_URL and MINION_ID are not secrets
# and are rendered into the command line; the node token is read at runtime
# from /etc/kri/node_token (written by base.heartbeat) so no secret ever lands
# in this world-readable config. Requires base.heartbeat to have been applied.
#
# Cross-platform (#673): the minion reload uses launchctl on macOS and systemctl
# on Linux, and the config file group is the OS-appropriate root group (wheel on
# macOS, root on Linux — Linux has no wheel group by default).

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set is_linux = grains['os_family'] in ['Debian', 'RedHat', 'Suse', 'Arch', 'Gentoo', 'Alpine'] %}

{% if ingest_url %}

kri_process_report_schedule_conf:
  file.managed:
    - name: /etc/salt/minion.d/kri-process-report.conf
    - user: root
    - group: {% if is_linux %}root{% else %}wheel{% endif %}
    - mode: "0644"
    - contents: |
        # kri process telemetry schedule — written by salt/states/base/process_report_schedule.sls
        # DO NOT EDIT: managed by kri. Remove this file to disable.
        schedule:
          kri_process_report:
            function: cmd.run
            args:
              - INGEST_URL={{ ingest_url | tojson }} MINION_ID={{ grains['id'] | tojson }} NODE_TOKEN=$(cat /etc/kri/node_token) python3 /opt/kri/process_collector.py
            seconds: 30
            enabled: True
            run_on_start: True

# Restart the minion (detached) so it picks up the new schedule from minion.d.
# Detached nohup: the restart must outlive the state run that triggers it.
{% if is_linux %}
kri_process_report_schedule_reload:
  cmd.run:
    - name: >
        nohup sh -c
        'sleep 3 &&
        systemctl restart salt-minion'
        >/dev/null 2>&1 &
    - onchanges:
        - file: kri_process_report_schedule_conf
{% else %}
kri_process_report_schedule_reload:
  cmd.run:
    - name: >
        nohup sh -c
        'sleep 3 &&
        launchctl stop com.saltstack.salt.minion &&
        sleep 2 &&
        launchctl start com.saltstack.salt.minion'
        >/dev/null 2>&1 &
    - onchanges:
        - file: kri_process_report_schedule_conf
{% endif %}

{% endif %}
