# salt/states/common/artifactory.sls
# Configures pip to use Artifactory PyPI proxy for offline package installation.
#
# Pillar keys:
#   artifactory:url           e.g. https://artifactory.internal
#   artifactory:pypi_proxy    e.g. https://artifactory.internal/artifactory/api/pypi/pypi-proxy/simple
#   artifactory:pip_trusted_host  e.g. artifactory.internal
#
# Usage (include in other state files):
#   include:
#     - common.artifactory

{% set af = pillar.get('artifactory', {}) %}
{% set pypi_proxy = af.get('pypi_proxy', 'https://artifactory.internal/artifactory/api/pypi/pypi-proxy/simple') %}
{% set pip_trusted_host = af.get('pip_trusted_host', 'artifactory.internal') %}

artifactory_pip_config:
  file.managed:
    - name: /etc/pip.conf
    - contents: |
        [global]
        index-url = {{ pypi_proxy }}
        trusted-host = {{ pip_trusted_host }}
        timeout = 120
    - user: root
    - group: wheel
    - mode: '0644'
