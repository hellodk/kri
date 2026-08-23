# salt/states/base/sbom_scan.sls
# Runs Syft on the node and uploads the CycloneDX JSON to the platform.
# Requires: syft installed at /usr/local/bin/syft, fleet_platform pillar configured.
#
# URL construction (#1047): pillar ingest_url already ends with the ingest
# prefix (see fleet_platform/workers/ansible_tasks.py), so appending only
# /sbom/<minion id> yields http://<master>/<ingest prefix>/sbom/<id>.
# Do NOT append the ingest prefix again here (double-prefix bug).
#
# Scan output (#1047): written to /var/run/kri-sbom-<minion id>.json — on Linux
# this is the root-only /run tmpfs; it replaces the predictable world-writable
# /tmp path. mktemp was considered but the filename must be shared across the
# scan/upload/cleanup states, so a deterministic path under /var/run is used.
# Skipped entirely when the fleet_platform pillar is absent (guard mirrors
# heartbeat.sls).
#
# Usage: salt '*' state.apply base.sbom_scan

{% if pillar.get('fleet_platform', {}).get('ingest_url', '') %}

sbom_scan_run:
  cmd.run:
    - name: |
        /usr/local/bin/syft packages \
          --scope all-layers \
          --output cyclonedx-json \
          / > /var/run/kri-sbom-{{ grains['id'] }}.json
    - timeout: 300

sbom_upload:
  module.run:
    - name: http.query
    - url: {{ pillar['fleet_platform']['ingest_url'] }}/sbom/{{ grains['id'] }}
    - method: POST
    - header_list:
        - "X-Node-Token: {{ pillar['fleet_platform']['node_token'] }}"
        - "Content-Type: application/json"
    - data: __slot__:salt:file.read(/var/run/kri-sbom-{{ grains['id'] }}.json)
    - require:
        - cmd: sbom_scan_run

sbom_cleanup:
  cmd.run:
    - name: rm -f /var/run/kri-sbom-{{ grains['id'] }}.json
    - require:
        - module: sbom_upload

{% endif %}
