# salt/states/ml/ollama/remove.sls
# Stops and removes the Ollama server launchd service.
# Does NOT delete the binary or downloaded models.
#
# Apply:
#   salt '*' state.apply ml.ollama.remove

{% set plist_label = 'com.kri.ollama' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}

ollama_server_unload:
  cmd.run:
    - name: launchctl unload {{ plist_path }} 2>/dev/null || true
    - onlyif: test -f {{ plist_path }}

ollama_server_plist_absent:
  file.absent:
    - name: {{ plist_path }}
    - require:
      - cmd: ollama_server_unload
