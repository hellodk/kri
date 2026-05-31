# salt/states/monitoring/node_exporter.sls
# Install and start Prometheus node_exporter on macOS nodes (arm64).
# Idempotent: skips download if /usr/local/bin/node_exporter already exists.
#
# Usage: salt '*' state.apply monitoring.node_exporter

{% set node_exporter_version = '1.8.2' %}
{% set install_dir = '/usr/local/bin' %}
{% set plist_path = '/Library/LaunchDaemons/io.prometheus.node_exporter.plist' %}
{% set archive = 'node_exporter-' ~ node_exporter_version ~ '.darwin-arm64.tar.gz' %}
{% set download_url = 'https://github.com/prometheus/node_exporter/releases/download/v' ~ node_exporter_version ~ '/' ~ archive %}

node_exporter_download:
  cmd.run:
    - name: |
        curl -fsSL "{{ download_url }}" -o /tmp/{{ archive }} && \
        tar -xf /tmp/{{ archive }} -C /tmp/ && \
        cp /tmp/node_exporter-{{ node_exporter_version }}.darwin-arm64/node_exporter {{ install_dir }}/node_exporter && \
        chmod 755 {{ install_dir }}/node_exporter && \
        rm -rf /tmp/{{ archive }} /tmp/node_exporter-{{ node_exporter_version }}.darwin-arm64
    - unless: test -f {{ install_dir }}/node_exporter

node_exporter_plist:
  file.managed:
    - name: {{ plist_path }}
    - mode: '0644'
    - contents: |
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>
          <string>io.prometheus.node_exporter</string>
          <key>ProgramArguments</key>
          <array>
            <string>{{ install_dir }}/node_exporter</string>
            <string>--web.listen-address=:9100</string>
          </array>
          <key>RunAtLoad</key>
          <true/>
          <key>KeepAlive</key>
          <true/>
          <key>StandardErrorPath</key>
          <string>/var/log/node_exporter.log</string>
          <key>StandardOutPath</key>
          <string>/var/log/node_exporter.log</string>
        </dict>
        </plist>
    - require:
      - cmd: node_exporter_download

node_exporter_service:
  cmd.run:
    - name: launchctl load {{ plist_path }}
    - unless: launchctl list | grep -q io.prometheus.node_exporter
    - require:
      - file: node_exporter_plist
