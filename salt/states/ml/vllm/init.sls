# salt/states/ml/vllm/init.sls
# Installs vLLM via Artifactory PyPI proxy and runs it as an OpenAI-compatible
# API server via launchd.
#
# Pillar keys:
#   artifactory:pypi_proxy    e.g. https://artifactory.internal/artifactory/api/pypi/pypi-proxy/simple
#   ml:vllm:version           (optional) pinned version, e.g. "0.4.0" (default: latest)
#   ml:vllm:port              (optional, default 8000) API port
#   ml:vllm:model             (optional, default microsoft/phi-2) model name for serving
#   ml:vllm:host              (optional, default 0.0.0.0) bind address
#
# Apply:
#   salt '*' state.apply ml.vllm
# Remove service:
#   salt '*' state.apply ml.vllm.remove

include:
  - common.artifactory

{% set vllm = pillar.get('ml', {}).get('vllm', {}) %}
{% set version = vllm.get('version', '') %}
{% set pkg = 'vllm==' ~ version if version else 'vllm' %}
{% set port = vllm.get('port', 8000) %}
{% set model = vllm.get('model', 'microsoft/phi-2') %}
{% set host = vllm.get('host', '0.0.0.0') %}
{% set plist_label = 'com.kri.vllm-server' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}
{% set log_dir = '/var/log/kri-vllm' %}
{% set pip_bin = '/usr/local/bin/pip3' %}
{% set python_bin = '/usr/local/bin/python3' %}

vllm_log_dir:
  file.directory:
    - name: {{ log_dir }}
    - makedirs: True
    - mode: '0755'

vllm_pip_install:
  cmd.run:
    - name: {{ pip_bin }} install --quiet {{ pkg }}
    - unless: {{ python_bin }} -c "import vllm" 2>/dev/null
    - require:
      - file: vllm_log_dir
      - file: artifactory_pip_config

vllm_server_plist:
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
                <string>{{ python_bin }}</string>
                <string>-m</string>
                <string>vllm.entrypoints.openai.api_server</string>
                <string>--model</string>
                <string>{{ model }}</string>
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
            <string>{{ log_dir }}/vllm.log</string>
            <key>StandardErrorPath</key>
            <string>{{ log_dir }}/vllm.err</string>
        </dict>
        </plist>
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - cmd: vllm_pip_install

vllm_server_service:
  cmd.run:
    - name: >
        launchctl unload {{ plist_path }} 2>/dev/null || true;
        launchctl load -w {{ plist_path }}
    - onchanges:
      - file: vllm_server_plist
    - require:
      - file: vllm_server_plist
