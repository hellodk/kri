# salt/states/ml/mlx_cluster/init.sls
# Installs MLX and mlx-lm via Artifactory PyPI proxy and configures the node
# as either a coordinator or worker in an MLX cluster.
#
# Pillar keys:
#   ml:mlx_cluster:role              (required) 'coordinator' or 'worker'
#   ml:mlx_cluster:coordinator_host  (required for worker) IP address of coordinator node
#   ml:mlx_cluster:port              (optional, default 5555) cluster communication port
#   artifactory:pypi_proxy           (required) e.g. https://artifactory.internal/artifactory/api/pypi/pypi-proxy/simple
#
# Apply:
#   salt '*' state.apply ml.mlx_cluster
# Remove state:
#   salt '*' state.apply ml.mlx_cluster.remove

include:
  - common.artifactory

{% set cluster = pillar.get('ml', {}).get('mlx_cluster', {}) %}
{% set role = cluster.get('role', 'worker') %}
{% set coordinator = cluster.get('coordinator_host', '127.0.0.1') %}
{% set port = cluster.get('port', 5555) %}

mlx_cluster_install:
  cmd.run:
    - name: /usr/local/bin/pip3 install --quiet mlx mlx-lm
    - unless: /usr/local/bin/python3 -c "import mlx_lm" 2>/dev/null
    - require:
      - file: artifactory_pip_config

mlx_cluster_config_dir:
  file.directory:
    - name: /etc/kri
    - makedirs: True
    - mode: '0755'

{% if role == 'coordinator' %}
mlx_cluster_config:
  file.managed:
    - name: /etc/kri/mlx-cluster.conf
    - contents: |
        ROLE=coordinator
        PORT={{ port }}
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - file: mlx_cluster_config_dir
{% else %}
mlx_cluster_config:
  file.managed:
    - name: /etc/kri/mlx-cluster.conf
    - contents: |
        ROLE=worker
        COORDINATOR={{ coordinator }}
        PORT={{ port }}
    - user: root
    - group: wheel
    - mode: '0644'
    - require:
      - file: mlx_cluster_config_dir
{% endif %}

mlx_cluster_ready:
  cmd.run:
    - name: /usr/local/bin/python3 -c "import mlx_lm; print('MLX cluster configured: role={{ role }}')"
    - require:
      - cmd: mlx_cluster_install
      - file: mlx_cluster_config
