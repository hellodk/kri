# salt/states/mlx/init.sls
# Installs Apple MLX and mlx-lm on Mac Mini nodes and runs a model as an
# OpenAI-compatible API server via launchd.
#
# Pillar keys:
#   mlx:model       (required) HuggingFace model ID, e.g. mlx-community/Llama-3.2-3B-Instruct-4bit
#   mlx:port        (optional, default 8080) port for mlx-lm serve
#   mlx:host        (optional, default 127.0.0.1) bind address — use 0.0.0.0 for fleet access
#   mlx:max_tokens  (optional, default 4096) max tokens per response
#   mlx:hf_token    (optional) HuggingFace token for gated models
#
# Apply to all nodes:
#   salt '*' state.apply mlx
# Apply to one node:
#   salt 'mac-mini-01' state.apply mlx
# Remove service:
#   salt '*' state.apply mlx.remove

{% set model    = pillar['mlx']['model'] %}
{% set port     = pillar.get('mlx', {}).get('port', 8080) %}
{% set host     = pillar.get('mlx', {}).get('host', '127.0.0.1') %}
{% set max_tok  = pillar.get('mlx', {}).get('max_tokens', 4096) %}
{% set hf_token = pillar.get('mlx', {}).get('hf_token', '') %}
{% set plist_label = 'com.kri.mlx-server' %}
{% set plist_path  = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}
{% set log_dir     = '/var/log/kri-mlx' %}
{% set pip_bin     = '/usr/local/bin/pip3' %}
{% set python_bin  = '/usr/local/bin/python3' %}

# ── Python / pip ──────────────────────────────────────────────────────────────

mlx_log_dir:
  file.directory:
    - name: {{ log_dir }}
    - makedirs: True
    - mode: '0755'

mlx_pip_install:
  cmd.run:
    - name: {{ pip_bin }} install --upgrade --quiet mlx mlx-lm huggingface-hub
    - unless: {{ python_bin }} -c "import mlx_lm" 2>/dev/null
    - require:
      - file: mlx_log_dir

{% if hf_token %}
mlx_hf_token:
  environ.setenv:
    - name: HUGGING_FACE_HUB_TOKEN
    - value: {{ hf_token }}
    - update_minion: True
{% endif %}

# ── Pre-download the model to the HuggingFace cache ──────────────────────────
# This can take several minutes on first run depending on model size.

mlx_model_download:
  cmd.run:
    - name: >
        {{ python_bin }} -m huggingface_hub.commands.huggingface_cli download
        {{ model }}
    - unless: >
        {{ python_bin }} -c "
        from huggingface_hub import snapshot_download, try_to_load_from_cache;
        import sys;
        p = try_to_load_from_cache('{{ model }}', 'config.json');
        sys.exit(0 if p else 1)"
    - timeout: 1800
    - require:
      - cmd: mlx_pip_install

# ── launchd plist ─────────────────────────────────────────────────────────────

mlx_server_plist:
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
                <string>mlx_lm.server</string>
                <string>--model</string>
                <string>{{ model }}</string>
                <string>--host</string>
                <string>{{ host }}</string>
                <string>--port</string>
                <string>{{ port | string }}</string>
                <string>--max-tokens</string>
                <string>{{ max_tok | string }}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{{ log_dir }}/mlx-server.log</string>
            <key>StandardErrorPath</key>
            <string>{{ log_dir }}/mlx-server.err</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>/usr/local/bin:/usr/bin:/bin</string>
                {% if hf_token %}
                <key>HUGGING_FACE_HUB_TOKEN</key>
                <string>{{ hf_token }}</string>
                {% endif %}
            </dict>
        </dict>
        </plist>
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - cmd: mlx_model_download

mlx_server_service:
  cmd.run:
    - name: >
        launchctl unload {{ plist_path }} 2>/dev/null || true;
        launchctl load -w {{ plist_path }}
    - onchanges:
      - file: mlx_server_plist
    - require:
      - file: mlx_server_plist
