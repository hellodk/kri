# salt/states/reactor/grain_report_on_start.sls
#
# Fires grain_report when any accepted minion starts or reconnects.
# Lives under salt/states/ so it is served via file_roots (salt://).
# The separate ../salt/reactor mount is NOT needed.
#
# Triggered by: salt/minion/*/start  (configured in salt-master.conf)
# Reference:    reactor: - 'salt/minion/*/start': - salt://reactor/grain_report_on_start.sls

report_grains_on_start:
  local.state.apply:
    # C2-fix: minion ID quoted to prevent YAML type-coercion for IDs starting
    # with digits or containing special characters (audit finding C2).
    - tgt: "{{ data['id'] }}"
    - arg:
      - base.grain_report
