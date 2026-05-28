# salt/pillar/artifactory.sls
# Artifactory repository configuration for offline package and binary distribution.
#
# This pillar is included by common.artifactory and consumed by all ML states
# to configure pip, download binaries, and pull pre-built artifacts.

artifactory:
  url: https://artifactory.internal
  pypi_proxy: https://artifactory.internal/artifactory/api/pypi/pypi-proxy/simple
  binary_repo: https://artifactory.internal/artifactory/binaries
  pip_trusted_host: artifactory.internal
