# salt/states/ml/ollama/init.sls
# Downloads Ollama binary from Artifactory binary repository and runs it
# as an OpenAI-compatible API server via launchd.
#
# Pillar keys:
#   artifactory:binary_repo   e.g. https://artifactory.internal/artifactory/binaries
#   ml:ollama:binary_url      (optional) full URL to Ollama binary — overrides binary_repo if set
#   ml:ollama:models          (optional) list of models to pre-pull, e.g. ['llama2', 'mistral']
#   ml:ollama:port            (optional, default 11434) API port
#
# Apply:
#   salt '*' state.apply ml.ollama
# Remove service:
#   salt '*' state.apply ml.ollama.remove

{% set binary_repo = pillar.get('artifactory', {}).get('binary_repo', 'https://artifactory.internal/artifactory/binaries') %}
{% set ollama = pillar.get('ml', {}).get('ollama', {}) %}
{% set binary_url = ollama.get('binary_url', binary_repo ~ '/ollama') %}
{% set models = ollama.get('models', []) %}
{% set port = ollama.get('port', 11434) %}
{% set plist_label = 'com.kri.ollama' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}
{% set log_dir = '/var/log/kri-ollama' %}
{% set binary_path = '/usr/local/bin/ollama' %}

ollama_log_dir:
  file.directory:
    - name: {{ log_dir }}
    - makedirs: True
    - mode: '0755'

ollama_binary_download:
  file.managed:
    - name: {{ binary_path }}
    - source: {{ binary_url }}
    - source_hash: ''
    - mode: '0755'
    - require:
      - file: ollama_log_dir

ollama_server_plist:
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
                <string>serve</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{{ log_dir }}/ollama.log</string>
            <key>StandardErrorPath</key>
            <string>{{ log_dir }}/ollama.err</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>OLLAMA_HOST</key>
                <string>127.0.0.1:{{ port | string }}</string>
            </dict>
        </dict>
        </plist>
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - file: ollama_binary_download

ollama_server_service:
  cmd.run:
    - name: >
        launchctl unload {{ plist_path }} 2>/dev/null || true;
        launchctl load -w {{ plist_path }}
    - onchanges:
      - file: ollama_server_plist
    - require:
      - file: ollama_server_plist

{% if models %}
# Pre-pull models after service is running
ollama_models_pull:
  cmd.run:
    - name: >
        sleep 5;
        {% for model in models %}
        {{ binary_path }} pull {{ model }} &&
        {% endfor %}
        true
    - require:
      - cmd: ollama_server_service
{% endif %}
