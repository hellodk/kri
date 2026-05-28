#!/bin/sh
# Salt-master startup — validates PKI keys exist before starting.
# Keys MUST be pre-seeded in the bind-mounted /etc/salt/pki/master/.
# This script never auto-generates keys: key stability = minion connectivity stability.
set -e

PKI=/etc/salt/pki/master

if [ ! -f "${PKI}/master.pem" ] || [ ! -f "${PKI}/master.pub" ]; then
    echo "FATAL: Salt master PKI keys not found in ${PKI}/"
    echo ""
    echo "On first deploy:"
    echo "  1. Run: kri pki-init   (generates keys and writes them to deploy/salt-pki/)"
    echo "  2. Back up deploy/salt-pki/master.pem to ansible vault"
    echo "  3. Commit deploy/salt-pki/master.pub (public key is not secret)"
    echo ""
    echo "On restore from backup:"
    echo "  ansible-playbook playbooks/restore_salt_pki.yml"
    echo ""
    echo "The master key MUST never change — changing it disconnects all minions."
    exit 1
fi

# Symlink master key to the versioned filename salt expects
MASTER_KEY_ID=$(sha1sum "${PKI}/master.pub" | awk '{print $1}' | cut -c1-8)
if [ ! -L "${PKI}/master.pem.link" ]; then
    # Salt creates its own symlinks on startup — just validate and proceed
    echo "[salt-master] PKI keys present (pub: $(head -2 ${PKI}/master.pub | tail -1 | cut -c1-20)...)"
fi

echo "[salt-master] Starting salt-master $(salt-master --version)"
exec /usr/bin/salt-master --log-level=info --log-file=/dev/stdout
