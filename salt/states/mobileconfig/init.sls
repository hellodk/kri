{%- set installed = grains.get('mobileconfig_installed', []) %}
{%- for uuid, xml in pillar.get('mobileconfig_profiles', {}).items() %}
{%- if uuid not in installed %}
install_profile_{{ uuid }}:
  cmd.run:
    - name: |
        cat > /tmp/kri_{{ uuid }}.mobileconfig << 'MCEOF'
        {{ xml }}
        MCEOF
        profiles install -path /tmp/kri_{{ uuid }}.mobileconfig
        rm -f /tmp/kri_{{ uuid }}.mobileconfig
    - unless: profiles list | grep -q {{ uuid }}
{%- endif %}
{%- endfor %}
