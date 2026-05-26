# salt/states/tart/remove.sls
# Stops and deletes all VMs defined in pillar.
# Run with:  salt '<target>' state.apply tart.remove
#
# This is destructive — VM disk images are permanently deleted.
# Pull the image again to recreate from scratch.

{% set tart_bin = '/opt/homebrew/bin/tart' %}
{% set run_user = pillar['tart']['run_user'] %}
{% set vms      = pillar.get('tart', {}).get('vms', {}) %}

{% for vm_name, vm in vms.items() %}

{% set label = 'com.tart.' ~ vm_name %}
{% set plist = '/Library/LaunchDaemons/' ~ label ~ '.plist' %}

tart_unload_{{ vm_name }}:
  cmd.run:
    - name: launchctl unload -w {{ plist }}
    - onlyif: launchctl list 2>/dev/null | grep -q '{{ label }}'

tart_stop_{{ vm_name }}:
  cmd.run:
    - name: {{ tart_bin }} stop {{ vm_name }} --timeout 30
    - onlyif: {{ tart_bin }} list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx '{{ vm_name }}'
    - runas: {{ run_user }}
    - require:
      - cmd: tart_unload_{{ vm_name }}

tart_delete_{{ vm_name }}:
  cmd.run:
    - name: {{ tart_bin }} delete {{ vm_name }}
    - onlyif: {{ tart_bin }} list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx '{{ vm_name }}'
    - runas: {{ run_user }}
    - require:
      - cmd: tart_stop_{{ vm_name }}

tart_plist_absent_{{ vm_name }}:
  file.absent:
    - name: {{ plist }}
    - require:
      - cmd: tart_unload_{{ vm_name }}

{% endfor %}
