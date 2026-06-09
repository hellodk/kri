# salt/states/base/process_report_schedule.sls
# Installs a persistent Salt schedule entry that runs base.process_report
# every 30 seconds on each minion.
#
# This writes a minion.d config file so the schedule survives cache clears
# and minion restarts (same pattern as heartbeat.sls).
#
# Apply once during bootstrap (or via highstate):
#   salt '*' state.apply base.process_report_schedule
#
# To disable: remove the file and restart the minion:
#   salt '*' file.remove /etc/salt/minion.d/kri-process-report.conf
#   salt '*' service.restart salt-minion

kri_process_report_schedule_conf:
  file.managed:
    - name: /etc/salt/minion.d/kri-process-report.conf
    - user: root
    - group: wheel
    - mode: "0644"
    - contents: |
        # kri process telemetry schedule — written by salt/states/base/process_report_schedule.sls
        # DO NOT EDIT: managed by kri. Remove this file to disable.
        schedule:
          kri_process_report:
            function: state.apply
            args:
              - base.process_report
            seconds: 30
            enabled: True
            run_on_start: True

# Restart the minion (detached) so it picks up the new schedule from minion.d.
# Detached nohup: the restart must outlive the state run that triggers it.
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
