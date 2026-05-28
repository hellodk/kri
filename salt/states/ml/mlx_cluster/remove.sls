# salt/states/ml/mlx_cluster/remove.sls
# Removes the MLX cluster configuration file.
# Does NOT uninstall mlx or mlx-lm packages.
#
# Apply:
#   salt '*' state.apply ml.mlx_cluster.remove

mlx_cluster_config_absent:
  file.absent:
    - name: /etc/kri/mlx-cluster.conf
