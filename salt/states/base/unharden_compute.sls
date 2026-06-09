# salt/states/base/unharden_compute.sls
# Exact inverse of salt/states/base/harden_compute.sls.
# Re-enables every service that harden_compute disabled, and restores Spotlight.
#
# Apply to reverse a previous harden run:
#   salt '*' state.apply base.unharden_compute
#
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  VALIDATE on one test mini before fleet-wide rollout.                   ║
# ║  After applying, reboot and confirm all expected services come back up.  ║
# ║  Run: sudo launchctl print-disabled system | grep <label>               ║
# ║  to verify the enable took effect in the system domain.                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# This state mirrors the disable_labels list in harden_compute.sls exactly.
# If you edit that list, edit this one identically so they remain a matched pair.
#
# "|| true" on every cmd maintains FAIL-TOLERANT behaviour — a label that was
# never actually disabled (e.g. didn't exist on this OS version) won't abort
# the enable run.

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

# --- Re-enable individual launchd services ---

{% for label in disable_labels %}
unharden_enable_{{ loop.index }}:
  cmd.run:
    - name: launchctl enable system/{{ label }} || true
    - onlyif: test -x /bin/launchctl || command -v launchctl
{% endfor %}

# --- Restore Spotlight indexing on the root volume ---
# Mirrors the mdutil -i off / in harden_compute.sls.
unharden_spotlight_on:
  cmd.run:
    - name: mdutil -i on / || true
    - onlyif: test -x /usr/bin/mdutil || command -v mdutil
