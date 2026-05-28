# salt/states/ml/vllm/remove.sls
# Stops and removes the vLLM server launchd service.
# Does NOT uninstall vllm or delete cached models.
#
# Apply:
#   salt '*' state.apply ml.vllm.remove

{% set plist_label = 'com.kri.vllm-server' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}

vllm_server_unload:
  cmd.run:
    - name: launchctl unload {{ plist_path }} 2>/dev/null || true
    - onlyif: test -f {{ plist_path }}

vllm_server_plist_absent:
  file.absent:
    - name: {{ plist_path }}
    - require:
      - cmd: vllm_server_unload
