# salt/states/mlx/remove.sls
# Stops and removes the MLX server launchd service.
# Does NOT uninstall mlx-lm or delete the model cache.
#
# Apply:
#   salt 'mac-mini-01' state.apply mlx.remove

{% set plist_label = 'com.kri.mlx-server' %}
{% set plist_path  = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}

mlx_server_unload:
  cmd.run:
    - name: launchctl unload {{ plist_path }} 2>/dev/null || true
    - onlyif: test -f {{ plist_path }}

mlx_server_plist_absent:
  file.absent:
    - name: {{ plist_path }}
    - require:
      - cmd: mlx_server_unload
