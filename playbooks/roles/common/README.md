# common

Normalizes OS/arch facts shared across all kri bootstrap roles:

| Fact | Meaning |
|------|---------|
| `cpu_arch` | `arm64` or `x86_64` |
| `ne_arch` | `arm64` or `amd64` (node_exporter release-asset naming) |
| `ne_os` | `darwin` or `linux` |
| `salt_call_bin` | Path to `salt-call` (`/opt/salt/salt-call` on macOS, `salt-call` on Linux) |
| `salt_group` | `wheel` on macOS, `root` on Linux |
| `brew_prefix` | Homebrew prefix for the detected `cpu_arch` (from `brew_prefix_arm64`/`brew_prefix_x86` in group_vars) |
| `brew_user` (macOS only) | The non-root user Homebrew commands should run as |

## Precondition: gathered facts required

This role reads `ansible_architecture` and `ansible_os_family` — it does **not**
gather facts itself. The play that consumes this role must gather facts first,
either via:

```yaml
- hosts: targets
  gather_facts: true
  roles:
    - common
```

or an explicit `setup:` task before including this role:

```yaml
- name: Gather OS and hardware facts
  ansible.builtin.setup:
    gather_subset: ['min', 'hardware']

- name: Include common role
  ansible.builtin.include_role:
    name: common
```

Per §9 #1 of the roles-refactor plan, `cpu_arch`/`ne_arch` are derived from the
gathered `ansible_architecture` fact — never from `raw: uname -m`.
