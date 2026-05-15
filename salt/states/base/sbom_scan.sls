# salt/states/base/sbom_scan.sls
# Runs Syft on the node and uploads the CycloneDX JSON to the platform.
# Requires: syft installed at /usr/local/bin/syft, fleet_platform pillar configured.
#
# Usage: salt '*' state.apply base.sbom_scan

sbom_scan_run:
  cmd.run:
    - name: |
        /usr/local/bin/syft packages \
          --scope all-layers \
          --output cyclonedx-json \
          / > /tmp/sbom-{{ grains['id'] }}.json
    - timeout: 300

sbom_upload:
  module.run:
    - name: http.query
    - url: {{ pillar['fleet_platform']['ingest_url'] }}/api/v1/ingest/sbom/{{ grains['id'] }}
    - method: POST
    - header_list:
        - "X-Node-Token: {{ pillar['fleet_platform']['node_token'] }}"
        - "Content-Type: application/json"
    - data: __slot__:salt:file.read(/tmp/sbom-{{ grains['id'] }}.json)
    - require:
        - cmd: sbom_scan_run

sbom_cleanup:
  cmd.run:
    - name: rm -f /tmp/sbom-{{ grains['id'] }}.json
    - require:
        - module: sbom_upload
