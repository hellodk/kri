# salt/states/base/grain_report.sls
# Reports current grain data to the Fleet Platform ingest API.
# Apply manually or via reactor on minion start:
#   salt '*' state.apply base.grain_report

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}

report_grains_to_fleet_platform:
  module.run:
    - name: http.query
    - url: {{ ingest_url }}/grains
    - method: POST
    - header_list:
        - "Content-Type: application/json"
        - "X-Node-Token: {{ node_token }}"
    - data: {{ {"minion_id": grains["id"], "grains": grains} | tojson }}
    - unless: test -z "{{ ingest_url }}"
