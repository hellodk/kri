# salt/states/common/config_profiles.sls
#
# Ensures macOS configuration profiles (.mobileconfig) are installed and consistent.
# kri serves profiles via its API; this state downloads and installs them.
#
# Apply with pillar specifying which profiles to install:
#   salt '*' state.apply common.config_profiles pillar='{"config_profiles": [{"id": "uuid", "bundle_id": "com.company.wifi"}]}'
#
# Or via top.sls for fleet-wide enforcement:
#   base:
#     'G@os:MacOS':
#       - common.config_profiles

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}
{% set profiles = pillar.get('config_profiles', []) %}

# Derive kri base URL from ingest URL (strip /api/v1/ingest suffix)
{% set kri_base = ingest_url | replace('/api/v1/ingest', '') if ingest_url else '' %}

{% if kri_base and profiles %}

{% for profile in profiles %}
{% set profile_id = profile.get('id', '') %}
{% set bundle_id = profile.get('bundle_id', '') %}
{% set profile_name = profile.get('name', bundle_id) %}

{% if profile_id and bundle_id %}

# Download profile from kri API
download_config_profile_{{ bundle_id | replace('.', '_') }}:
  cmd.run:
    - name: >
        python3 -c "
        import urllib.request
        req = urllib.request.Request(
            '{{ kri_base }}/api/v1/config-profiles/{{ profile_id }}/content',
            headers={'X-Node-Token': '{{ node_token }}'},
        )
        data = urllib.request.urlopen(req, timeout=30).read()
        open('/tmp/kri_profile_{{ bundle_id | replace('.', '_') }}.mobileconfig', 'wb').write(data)
        print('downloaded')
        "
    - unless: profiles list -output xml | python3 -c "import sys; data=sys.stdin.read(); exit(0 if '{{ bundle_id }}' in data else 1)"
    - require_in:
      - cmd: install_config_profile_{{ bundle_id | replace('.', '_') }}

# Install profile (sudo required — profiles command needs elevated privileges)
install_config_profile_{{ bundle_id | replace('.', '_') }}:
  cmd.run:
    - name: profiles install -path /tmp/kri_profile_{{ bundle_id | replace('.', '_') }}.mobileconfig
    - unless: profiles list -output xml | python3 -c "import sys; data=sys.stdin.read(); exit(0 if '{{ bundle_id }}' in data else 1)"
    - runas: root

# Verify installation
verify_config_profile_{{ bundle_id | replace('.', '_') }}:
  cmd.run:
    - name: profiles list | grep '{{ bundle_id }}'
    - require:
      - cmd: install_config_profile_{{ bundle_id | replace('.', '_') }}

# Clean up temp file
cleanup_config_profile_{{ bundle_id | replace('.', '_') }}:
  file.absent:
    - name: /tmp/kri_profile_{{ bundle_id | replace('.', '_') }}.mobileconfig
    - require:
      - cmd: verify_config_profile_{{ bundle_id | replace('.', '_') }}

{% endif %}
{% endfor %}

{% elif not kri_base %}
config_profiles_no_ingest_url:
  test.fail_without_changes:
    - name: "config_profiles requires fleet_platform.ingest_url in pillar"

{% else %}
config_profiles_none_specified:
  test.nop:
    - name: "No config_profiles specified in pillar — nothing to install"

{% endif %}


# ── Removal: ensure profiles NOT in the desired list are removed ──────────────
# Set config_profiles_remove in pillar to remove specific profiles.
{% set profiles_to_remove = pillar.get('config_profiles_remove', []) %}

{% for profile in profiles_to_remove %}
{% set bundle_id = profile.get('bundle_id', '') %}
{% if bundle_id %}

remove_config_profile_{{ bundle_id | replace('.', '_') }}:
  cmd.run:
    - name: profiles remove -identifier '{{ bundle_id }}'
    - onlyif: profiles list | grep '{{ bundle_id }}'

{% endif %}
{% endfor %}
