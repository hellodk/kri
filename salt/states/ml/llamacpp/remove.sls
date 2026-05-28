# salt/states/ml/llamacpp/remove.sls
# Stops and removes the llama.cpp server launchd service.
# Does NOT delete the binary or model files.
#
# Apply:
#   salt '*' state.apply ml.llamacpp.remove

{% set plist_label = 'com.kri.llamacpp-server' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}

llamacpp_server_unload:
  cmd.run:
    - name: launchctl unload {{ plist_path }} 2>/dev/null || true
    - onlyif: test -f {{ plist_path }}

llamacpp_server_plist_absent:
  file.absent:
    - name: {{ plist_path }}
    - require:
      - cmd: llamacpp_server_unload
