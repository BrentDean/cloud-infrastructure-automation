# Linux security controls and evidence boundaries

This repository uses two deliberately separate hardening profiles.

## AWS Ubuntu baseline

The current AWS design applies an Ansible-managed Linux baseline to the
ephemeral Ubuntu hosts in addition to AWS security groups:

- SSH: `PermitRootLogin no`, password and keyboard-interactive authentication
  disabled, public-key authentication enabled.
- Host firewall: UFW default-deny inbound with source-specific allow rules that
  mirror the intended web/app/broker/DB paths.
- Audit: auditd enabled, disk logging required, and watches on SSH configuration,
  UFW configuration, and local systemd unit configuration.
- Evidence: a dedicated playbook verifies effective SSH settings, firewall
  state and audit rules, then writes one sanitized JSON record per host into
  the private per-run evidence directory.
- Idempotency: the live runner executes hardening twice and requires the second
  pass to report `changed=0`.

The k3s application host is a deliberate firewall exception: UFW ownership is
disabled there because k3s manages node/container packet-filter rules. AWS
security groups still restrict the k3s NodePort to the web tier. SSH and audit
hardening still apply to that host. This avoids claiming a host-firewall policy
that has not been proven compatible with the cluster network.

These controls are relevant to NIST SP 800-53 Rev. 5 engineering themes such
as AC-17 (remote access), SC-7 (boundary protection), CM-6 (configuration
settings) and AU-12 (audit record generation). This is a technical control
mapping, **not** a formal NIST assessment or authorization.

NIST reference:
https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final

## Selected RHEL 9 STIG-aligned profile

`ansible/rhel9-security/selected-hardening.yml` is a separate lab profile for
the RHEL 9 VM. It is intentionally a **selected-control exercise, not a full STIG
implementation, not a full STIG checklist, and not a compliance certification**.

The selected alignment target is DISA RHEL 9 STIG V2R9 (May 20, 2026):

| Finding | Selected behavior in this lab |
| --- | --- |
| V-258078 / RHEL-09-431010 | SELinux runtime must be Enforcing |
| V-258079 / RHEL-09-431015 | SELinux policy must be targeted |
| V-257935 / RHEL-09-251010 | firewalld package installed |
| V-257936 / RHEL-09-251015 | firewalld service active |
| V-258152 / RHEL-09-653015 | auditd service enabled/active |
| V-258170 / RHEL-09-653105 | auditd `write_logs = yes` |
| V-257985 / RHEL-09-255045 | direct root SSH login prohibited |
| V-258074 / RHEL-09-412065 | default `UMASK 077` |
| V-258171 / RHEL-09-653110 | audit configuration files mode 0600 |

The playbook also installs `policycoreutils`, refuses to report success when
SELinux is disabled at runtime, validates `sshd` syntax, explicitly keeps SSH
permitted through firewalld, and performs runtime assertions for the selected
settings.

Current evidence boundary: GitHub Actions performs YAML/Ansible syntax and
static contract validation for this RHEL profile. It **does not** provide an
RHEL kernel with SELinux enforcement, so SELinux/firewalld/audit runtime evidence
must come from the separate RHEL 9 VM exercise before those controls are claimed
as live-verified.

DISA STIG reference index:
https://www.stigviewer.com/stigs/red_hat_enterprise_linux_9/versions
