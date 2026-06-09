# salt/states/base/harden_compute.sls
# Disables a CONSERVATIVE set of unneeded macOS launchd services on headless
# compute minis to reclaim CPU and memory for LLM / exo workloads.
#
# Mechanism: launchctl disable system/<label> — persists across reboots.
# The "|| true" on every cmd makes each step FAIL-TOLERANT: if a label does not
# exist on a particular OS version, or lives in a different domain (user vs
# system), the state run continues rather than aborting.
#
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ⚠  VALIDATE EACH LABEL ON ONE TEST MINI BEFORE FLEET ROLLOUT  ⚠       ║
# ║                                                                          ║
# ║  macOS service labels vary by OS version.  Some labels in this list      ║
# ║  live in the USER domain (launchctl disable user/<uid>/<label>), not     ║
# ║  system/, so a system/ disable will silently no-op.  SIP may prevent     ║
# ║  disabling a handful of Apple-signed system agents.                      ║
# ║                                                                          ║
# ║  Recommended validation procedure on one test mini:                      ║
# ║    1. Apply: salt '<test-mini>' state.apply base.harden_compute           ║
# ║    2. Reboot and confirm exo/LLM workloads still start cleanly.          ║
# ║    3. Verify each disabled service is actually gone:                     ║
# ║         sudo launchctl print-disabled system | grep <label>              ║
# ║    4. Roll back if anything unexpected: salt '<test-mini>' state.apply   ║
# ║         base.unharden_compute                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Reversal (full restore): salt '*' state.apply base.unharden_compute
#
# NEVER-disable list (not included here — keep it that way):
#   salt-minion, salt-master, sshd, mDNSResponder, configd, powerd, securityd,
#   trustd, opendirectoryd, syslogd, networkd, exo

{% set disable_labels = [
  "com.apple.assistantd",
  "com.apple.Siri.agent",
  "com.apple.siriknowledged",
  "com.apple.parsecd",
  "com.apple.photoanalysisd",
  "com.apple.photolibraryd",
  "com.apple.mediaanalysisd",
  "com.apple.gamed",
  "com.apple.ScreenTimeAgent",
  "com.apple.AirPlayXPCHelper",
  "com.apple.analyticsd",
  "com.apple.osanalytics.osanalyticshelper",
  "com.apple.suggestd",
  "com.apple.knowledgeconstructiond",
  "com.apple.ap.adprivacyd",
] %}

# --- Disable individual launchd services ---
# Each state ID is unique via loop.index.
# "|| true" ensures a missing / wrong-domain label cannot break the run.

{% for label in disable_labels %}
harden_disable_{{ loop.index }}:
  cmd.run:
    - name: launchctl disable system/{{ label }} || true
    - onlyif: test -x /bin/launchctl || command -v launchctl
{% endfor %}

# --- Disable Spotlight indexing on the root volume ---
# Uses mdutil (different mechanism from launchctl disable).
# Spotlight is a significant CPU/IO drain on minis that serve no search users.
# Reversal: salt '*' state.apply base.unharden_compute (runs mdutil -i on /)
harden_spotlight_off:
  cmd.run:
    - name: mdutil -i off / || true
    - onlyif: test -x /usr/bin/mdutil || command -v mdutil
