#!/bin/sh
# Salt-master startup — ensures a stable PKI key across container restarts.
#
# M-1 fix (SRE audit root cause): salt intentionally "locks" its private key
# to mode 200 (write-only) after loading it. On the next startup it finds the
# file unreadable and REGENERATES — breaking all minion connections.
#
# Solution: keep a protected backup (.kri_backup_master.pem) that salt never
# touches. On every startup, restore a fresh copy from the backup with correct
# permissions (mode 400, owned by salt). Salt reads the fresh copy, uses the
# SAME key every time, and locks it again. The backup is untouched.
set -e

PKI=/etc/salt/pki/master
SALT_UID=999
SALT_GID=999
BACKUP_PEM="${PKI}/.kri_backup_master.pem"
BACKUP_PUB="${PKI}/.kri_backup_master.pub"
KEYID="kri_stable"

# ── 1. Validate source keys exist ─────────────────────────────────────────────
if [ ! -e "${PKI}/master.pem" ] && [ ! -f "${BACKUP_PEM}" ]; then
    echo "FATAL: No PKI keys found — neither master.pem nor backup exists."
    echo "Run: kri pki-init"
    exit 1
fi

# ── 2. Create / update the backup from source keys ────────────────────────────
# The backup is our canonical read-only copy that salt never modifies.
if [ ! -f "${BACKUP_PEM}" ]; then
    # First run: source is a plain master.pem (or old symlink pointing to a file)
    SRC_PEM=$(readlink -f "${PKI}/master.pem" 2>/dev/null || echo "${PKI}/master.pem")
    SRC_PUB=$(readlink -f "${PKI}/master.pub" 2>/dev/null || echo "${PKI}/master.pub")
    if [ -f "$SRC_PEM" ] && [ -f "$SRC_PUB" ]; then
        cp "$SRC_PEM" "${BACKUP_PEM}"
        cp "$SRC_PUB" "${BACKUP_PUB}"
        chmod 400 "${BACKUP_PEM}"
        chmod 444 "${BACKUP_PUB}"
        echo "[pki-init] Backup created from $(basename ${SRC_PEM})"
    else
        echo "FATAL: Cannot read source key file for backup creation"
        exit 1
    fi
fi

# ── 3. Restore active key from backup (fresh copy with correct permissions) ───
# This is the core of the fix: even if salt locked kri_stable.pem to mode 200
# on the previous run, we overwrite it with a readable copy from backup.
cp "${BACKUP_PEM}" "${PKI}/${KEYID}.pem"
cp "${BACKUP_PUB}" "${PKI}/${KEYID}.pub"
chown ${SALT_UID}:${SALT_GID} "${PKI}/${KEYID}.pem" "${PKI}/${KEYID}.pub"
chmod 400 "${PKI}/${KEYID}.pem"
chmod 444 "${PKI}/${KEYID}.pub"

# ── 4. Set master.pem / master.pub symlinks to point to our stable key ────────
# If they already exist (from salt's previous run pointing to a different key),
# we force-replace them with our stable key symlinks.
ln -sf "${PKI}/${KEYID}.pem" "${PKI}/master.pem.new"
ln -sf "${PKI}/${KEYID}.pub" "${PKI}/master.pub.new"
mv "${PKI}/master.pem.new" "${PKI}/master.pem"
mv "${PKI}/master.pub.new" "${PKI}/master.pub"

# ── 5. Remove all OTHER versioned key files ───────────────────────────────────
# Previous regenerated keys that salt cannot read cause it to generate yet more.
# We keep only our stable key.
for f in "${PKI}"/*.pem "${PKI}"/*.pub; do
    [ -e "$f" ] || continue
    [ -L "$f" ] && continue                  # keep symlinks (master.pem/pub)
    basename=$(basename "$f")
    case "$basename" in
        "${KEYID}.pem"|"${KEYID}.pub") continue ;;  # keep our key
        .kri_backup*) continue ;;             # keep backup (dot-file, salt ignores)
    esac
    echo "[pki-cleanup] Removing stale key: ${basename}"
    rm -f "$f"
done

# ── 6. Fix directory permissions for API container access ─────────────────────
chmod 755 "${PKI}" 2>/dev/null || true
for sub in minions minions_pre minions_rejected minions_denied minions_autosign; do
    mkdir -p "${PKI}/${sub}"
    chmod 755 "${PKI}/${sub}" 2>/dev/null || true
done

# ── 7. Verify and start ────────────────────────────────────────────────────────
# Verify salt can read the key (as the salt user, not as root)
if su -s /bin/sh -c "test -r '${PKI}/${KEYID}.pem'" salt 2>/dev/null; then
    echo "[salt-master] PKI ready — key: ${KEYID} (stable, no regeneration)"
else
    echo "WARN: salt user cannot read the key — salt may regenerate on this start"
fi

echo "[salt-master] Starting $(salt-master --version)"
/usr/bin/salt-master --log-level=info --log-file=/dev/stdout &
SALT_MASTER_PID=$!

echo "[salt-api] Waiting for salt-master to initialise..."
sleep 8

echo "[salt-api] Starting salt-api"
/usr/bin/salt-api --log-level=info --log-file=/dev/stdout &
SALT_API_PID=$!

# Exit if either child exits so dumb-init can restart the container.
wait -n $SALT_MASTER_PID $SALT_API_PID 2>/dev/null || {
    # wait -n not available on older shells — fall back to a poll loop
    while kill -0 $SALT_MASTER_PID 2>/dev/null && kill -0 $SALT_API_PID 2>/dev/null; do
        sleep 5
    done
}
echo "[entrypoint] A process exited — shutting down"
kill $SALT_MASTER_PID $SALT_API_PID 2>/dev/null
wait
