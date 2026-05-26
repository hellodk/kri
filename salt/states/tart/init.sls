# salt/states/tart/init.sls
# Installs tart and creates/starts VMs defined in pillar.
#
# Required pillar keys:
#   tart.run_user  — macOS user who owns ~/.tart/ (e.g. "dk")
#   tart.vms       — map of vm_name → vm config (see pillar/tart.sls.example)
#
# Supports both macOS (ghcr.io/cirruslabs/macos-*) and
# Linux (ghcr.io/cirruslabs/ubuntu) images.
# Requires Apple Silicon host running macOS 13+.

{% set tart_bin    = '/opt/homebrew/bin/tart' %}
{% set brew_bin    = '/opt/homebrew/bin/brew' %}
{% set run_user    = pillar['tart']['run_user'] %}
{% set vms         = pillar.get('tart', {}).get('vms', {}) %}

# ── 1. Install tart ────────────────────────────────────────────────────────

tart_tap:
  cmd.run:
    - name: {{ brew_bin }} tap cirruslabs/cli
    - unless: {{ brew_bin }} tap | grep -q 'cirruslabs/cli'
    - runas: {{ run_user }}

tart_install:
  cmd.run:
    - name: {{ brew_bin }} install cirruslabs/cli/tart
    - unless: test -x {{ tart_bin }}
    - runas: {{ run_user }}
    - require:
      - cmd: tart_tap

# ── 2. Per-VM states ───────────────────────────────────────────────────────

{% for vm_name, vm in vms.items() %}
{% if vm.get('enabled', True) %}

{% set cpu    = vm.get('cpu', 2) %}
{% set memory = vm.get('memory', 4096) %}
{% set disk   = vm.get('disk', 20) %}
{% set image  = vm['image'] %}
{% set label  = 'com.tart.' ~ vm_name %}
{% set plist  = '/Library/LaunchDaemons/' ~ label ~ '.plist' %}

# Clone from remote image — tart pulls the image automatically if not cached.
# Large images (macOS ~20 GB) may take several minutes on first run.
tart_clone_{{ vm_name }}:
  cmd.run:
    - name: {{ tart_bin }} clone {{ image }} {{ vm_name }}
    - unless: {{ tart_bin }} list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx '{{ vm_name }}'
    - runas: {{ run_user }}
    - timeout: 3600
    - require:
      - cmd: tart_install

# Set CPU / memory / disk — only on first creation (onchanges from clone).
# tart requires the VM to be stopped, which it is before the daemon starts.
tart_set_{{ vm_name }}:
  cmd.run:
    - name: >-
        {{ tart_bin }} set {{ vm_name }}
        --cpu {{ cpu }}
        --memory {{ memory }}
        --disk {{ disk }}
    - onchanges:
      - cmd: tart_clone_{{ vm_name }}
    - runas: {{ run_user }}

# launchd daemon: keeps the VM running at boot, restarts on unexpected exit.
# UserName causes launchd to run tart as run_user so ~/.tart/ is accessible.
tart_plist_{{ vm_name }}:
  file.managed:
    - name: {{ plist }}
    - source: salt://tart/files/com.tart.vm.plist.jinja
    - template: jinja
    - context:
        vm_name: {{ vm_name }}
        tart_bin: {{ tart_bin }}
        run_user: {{ run_user }}
        label: {{ label }}
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - cmd: tart_install

tart_service_{{ vm_name }}:
  cmd.run:
    - name: launchctl load -w {{ plist }}
    - unless: launchctl list 2>/dev/null | grep -q '{{ label }}'
    - require:
      - file: tart_plist_{{ vm_name }}
      - cmd: tart_set_{{ vm_name }}

{% endif %}
{% endfor %}
