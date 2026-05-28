# salt/states/ml/llamacpp/init.sls
# Downloads pre-compiled llama.cpp binary from Artifactory and runs it as
# an OpenAI-compatible API server via launchd.
#
# Pillar keys:
#   artifactory:binary_repo   e.g. https://artifactory.internal/artifactory/binaries
#   ml:llamacpp:binary_url    (optional) full URL to binary — overrides binary_repo if set
#   ml:llamacpp:model_path    (required) path to GGUF model file on node
#   ml:llamacpp:port          (optional, default 8080) API port
#   ml:llamacpp:host          (optional, default 0.0.0.0) bind address
#
# Apply:
#   salt '*' state.apply ml.llamacpp
# Remove service:
#   salt '*' state.apply ml.llamacpp.remove

{% set binary_repo = pillar.get('artifactory', {}).get('binary_repo', 'https://artifactory.internal/artifactory/binaries') %}
{% set llamacpp = pillar.get('ml', {}).get('llamacpp', {}) %}
{% set binary_url = llamacpp.get('binary_url', binary_repo ~ '/llama-cpp-server') %}
{% set model_path = llamacpp['model_path'] %}
{% set port = llamacpp.get('port', 8080) %}
{% set host = llamacpp.get('host', '0.0.0.0') %}
{% set plist_label = 'com.kri.llamacpp-server' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}
{% set log_dir = '/var/log/kri-llamacpp' %}
{% set binary_path = '/usr/local/bin/llama-server' %}

llamacpp_log_dir:
  file.directory:
    - name: {{ log_dir }}
    - makedirs: True
    - mode: '0755'

llamacpp_binary_download:
  file.managed:
    - name: {{ binary_path }}
    - source: {{ binary_url }}
    - source_hash: ''
    - mode: '0755'
    - require:
      - file: llamacpp_log_dir

llamacpp_server_plist:
  file.managed:
    - name: {{ plist_path }}
    - contents: |
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
            "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{{ plist_label }}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{{ binary_path }}</string>
                <string>-m</string>
                <string>{{ model_path }}</string>
                <string>--host</string>
                <string>{{ host }}</string>
                <string>--port</string>
                <string>{{ port | string }}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{{ log_dir }}/llamacpp.log</string>
            <key>StandardErrorPath</key>
            <string>{{ log_dir }}/llamacpp.err</string>
        </dict>
        </plist>
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - file: llamacpp_binary_download

llamacpp_server_service:
  cmd.run:
    - name: >
        launchctl unload {{ plist_path }} 2>/dev/null || true;
        launchctl load -w {{ plist_path }}
    - onchanges:
      - file: llamacpp_server_plist
    - require:
      - file: llamacpp_server_plist
