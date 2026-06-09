# salt_master Ansible Role

Installs, configures, and maintains `salt-master` + `salt-api` on a macOS or Linux host.

Designed to be **fully idempotent** — running the role against an already-provisioned host is safe. Only changed files trigger handler restarts.

---

## What the role does

1. **Installs** Salt from the bundled air-gapped `.pkg` (macOS) or the SaltProject apt/yum repo (Linux).
2. **Configures** `/etc/salt/master.d/kri.conf` — interface bind, pillar/file roots, presence events, reactor, `netapi_enable_clients`, and the `external_auth` ACL that authorises kri workers via PAM.
3. **Configures** `/etc/salt/master.d/salt-api.conf` — `rest_cherrypy` on `{{ salt_api_port }}` (default 8080) with TLS.
4. **Writes PKI** — copies the pre-generated master keypair so all existing minions continue trusting the master without re-acceptance.
5. **Creates the kri service account** (`krisalt`) and sets the salt-api password via PAM.
6. **Generates a self-signed TLS cert/key** for salt-api (idempotent — only once).
7. **Manages the service** via launchd plists (macOS) or systemd units (Linux).
8. **Verifies** salt-master (port 4505) and salt-api (port 8080) are accepting connections, then performs a live `POST /login` eauth probe to confirm the `external_auth` ACL is active.

---

## Sudo / become prerequisite

**The SSH user on the target host must have passwordless `sudo` (or you must pass the sudo password at runtime).**

Every privileged task in this role (`template`, `file`, `shell`, `user`, `command`) uses `become: true`. The role does **not** embed any hardcoded privilege-escalation password.

### Option A — passwordless sudo (recommended for mm1)

Add to `/etc/sudoers` (or `/etc/sudoers.d/ansible`) on the target:

```
dk ALL=(ALL) NOPASSWD: ALL
```

Then run without any extra flag:

```bash
ansible-playbook playbooks/deploy_salt_master_mm1.yml \
  -i playbooks/inventory/hosts.ini \
  -e "kri_salt_api_password=<secure-password>"
```

Or via the unified CLI:

```bash
scripts/kri saltmaster install 192.168.1.64
```

### Option B — interactive sudo prompt

If passwordless sudo is not configured, pass the become password at runtime:

```bash
ansible-playbook playbooks/deploy_salt_master_mm1.yml \
  -i playbooks/inventory/hosts.ini \
  -e "kri_salt_api_password=<secure-password>" \
  --ask-become-pass
```

---

## Re-applying the role against mm1 (already-provisioned host)

Running the role again when nothing has changed is a no-op — all tasks report `ok`, no handlers fire, no services restart.

When `kri.conf` or `salt-api.conf` changes (e.g. after adding a new function to the `external_auth` ACL), the role:

1. Writes the updated config (reports `changed`).
2. Triggers **both** `Restart salt-master` and `Restart salt-api` handlers (salt-api reads master.d config at startup, so both must restart for `external_auth` changes to take effect).
3. Waits for both ports to come back up.
4. Probes `POST /login` to confirm the new ACL is live.

**Exact re-apply command (mm1, macOS):**

```bash
ansible-playbook playbooks/deploy_salt_master_mm1.yml \
  -i playbooks/inventory/hosts.ini \
  -e "kri_salt_api_password=<secure-password>"
```

Or via the unified CLI (interactive mode — prompts for IP and password):

```bash
scripts/kri saltmaster install 192.168.1.64
```

---

## Role variables

All variables are defined in `defaults/main.yml` with documented descriptions.

| Variable | Default | Description |
|---|---|---|
| `salt_version` | `3007.14` | Salt version to install. Must match fleet minions. |
| `salt_api_port` | `8080` | salt-api HTTPS port. |
| `salt_api_user` | `krisalt` | PAM service account for kri workers. |
| `kri_salt_api_password` | `changeme-set-in-vault` | **Must be overridden.** Pass via `-e` or Vault. |
| `salt_master_interface` | `0.0.0.0` | Interface salt-master binds on. |
| `salt_api_ssl_crt` | `/etc/salt/pki/api/salt-api.crt` | TLS cert path. Auto-generated if absent. |
| `salt_api_ssl_key` | `/etc/salt/pki/api/salt-api.key` | TLS key path. Auto-generated if absent. |
| `salt_api_verify` | `true` | Set to `false` to skip the `/login` readiness probe. |

---

## Post-install verification (`tasks/verify.yml`)

The role always runs `tasks/verify.yml` at the end:

1. `wait_for port=4505` — salt-master ZeroMQ bus ready (60s timeout).
2. `wait_for port={{ salt_api_port }}` — salt-api HTTPS ready (60s timeout).
3. `uri POST /login eauth=pam` — proves `external_auth` ACL is live. A 200 response with a token means kri workers can authenticate.

To skip the login probe (e.g. during a CI dry-run where `kri_salt_api_password` is not set):

```bash
ansible-playbook playbooks/deploy_salt_master_mm1.yml \
  -i playbooks/inventory/hosts.ini \
  -e "kri_salt_api_password=<pw>" \
  -e "salt_api_verify=false"
```

---

## external_auth ACL sync requirement

The `external_auth` function list in `templates/kri-master.conf.j2` **must stay in sync** with `_DEFAULT_SALT_FUNCTIONS` in `fleet_platform/services/platform_settings_svc.py`. Any function added to the app-side allowlist must also appear in the ACL, or salt-api will return a 401 for that function.

After adding a new function:
1. Update both files in the same commit.
2. Re-apply the role against all salt-master hosts (the verification probe will confirm the new function is authorised).
