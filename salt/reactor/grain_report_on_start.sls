# salt/reactor/grain_report_on_start.sls
#
# Fires grain_report when any accepted minion starts or reconnects.
# This ensures kri marks the node "online" immediately on reconnect
# without waiting for the 5-minute heartbeat window.
#
# Triggered by: salt/minion/*/start  (configured in salt-master.conf)
#
# The minion ID is available as {{ data['id'] }} from the event data.

report_grains_on_start:
  local.state.apply:
    - tgt: {{ data['id'] }}
    - arg:
      - base.grain_report
