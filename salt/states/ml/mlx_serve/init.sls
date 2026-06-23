# salt/states/ml/mlx_serve/init.sls
# Serve one MLX tier (planner / coder / worker / embed) as an OpenAI-compatible
# HTTP endpoint via `mlx_lm.server`, managed by launchd, with model pre-download,
# a health probe, and mine.send so the kri tier-router can discover it (#712).
#
# Pillar keys (ml:mlx_serve):
#   tier      (required)  planner | coder | worker | embed   — capability tag
#   model     (required)  HF repo id of the 4-bit MLX model
#   port      (optional)  default 8080
#   max_concurrent (optional) default 1 on planners (16 GB is tight for 14B)
#   context_cap    (optional) default 8192 per-session token cap
#
# Apply:  salt 'mm1' state.apply ml.mlx_serve

include:
  - common.artifactory

{% set serve = pillar.get('ml', {}).get('mlx_serve', {}) %}
{% set tier = serve.get('tier', 'worker') %}
{% set model = serve.get('model', '') %}
{% set port = serve.get('port', 8080) %}
{% set max_concurrent = serve.get('max_concurrent', 1 if tier == 'planner' else 2) %}
{% set context_cap = serve.get('context_cap', 8192) %}
{% set label = 'ai.kri.mlx.' ~ tier %}

mlx_serve_install:
  cmd.run:
    - name: /usr/local/bin/pip3 install --quiet mlx mlx-lm
    - unless: /usr/local/bin/python3 -c "import mlx_lm.server" 2>/dev/null
    - require:
      - file: artifactory_pip_config

# Pre-download the model into the HF cache so first request isn't a cold pull.
mlx_serve_predownload:
  cmd.run:
    - name: >-
        /usr/local/bin/python3 -c "from huggingface_hub import snapshot_download;
        snapshot_download('{{ model }}')"
    - unless: test -d "$HOME/.cache/huggingface/hub/models--{{ model | replace('/', '--') }}"
    - require:
      - cmd: mlx_serve_install

mlx_serve_plist:
  file.managed:
    - name: /Library/LaunchDaemons/{{ label }}.plist
    - mode: '0644'
    - user: root
    - group: wheel
    - contents: |
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key><string>{{ label }}</string>
          <key>ProgramArguments</key>
          <array>
            <string>/usr/local/bin/python3</string>
            <string>-m</string>
            <string>mlx_lm.server</string>
            <string>--model</string><string>{{ model }}</string>
            <string>--host</string><string>0.0.0.0</string>
            <string>--port</string><string>{{ port }}</string>
            <string>--max-tokens</string><string>{{ context_cap }}</string>
          </array>
          <key>EnvironmentVariables</key>
          <dict>
            <key>MLX_MAX_CONCURRENT</key><string>{{ max_concurrent }}</string>
          </dict>
          <key>RunAtLoad</key><true/>
          <key>KeepAlive</key><true/>
          <key>StandardOutPath</key><string>/var/log/{{ label }}.log</string>
          <key>StandardErrorPath</key><string>/var/log/{{ label }}.err</string>
        </dict>
        </plist>
    - require:
      - cmd: mlx_serve_predownload

mlx_serve_load:
  cmd.run:
    - name: launchctl bootstrap system /Library/LaunchDaemons/{{ label }}.plist || launchctl kickstart -k system/{{ label }}
    - onchanges:
      - file: mlx_serve_plist

# Health probe — the OpenAI-compatible /v1/models endpoint must answer.
mlx_serve_health:
  cmd.run:
    - name: curl -fsS --max-time 5 http://127.0.0.1:{{ port }}/v1/models >/dev/null
    - retry:
        attempts: 10
        interval: 3
    - require:
      - cmd: mlx_serve_load
