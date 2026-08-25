# Gold / Paycheck staged deployment acceptance (redacted template)

> Template only. Replace bracketed values locally. Do not commit hostnames, IPs, certificate fingerprints, gateway identities, usernames, or key paths.

## Release envelope

- Candidate commit: `[LOCAL_COMMIT_SHA]`
- Gold platform/build: `[PLATFORM_AND_VERSION]`
- Paycheck platform/build: `[PLATFORM_AND_VERSION]`
- Installer run without activation on both endpoints: `[PASS/FAIL + timestamp]`
- `doctor --json` archived in the private change record (review for path disclosure before sharing): `[ARTIFACT_REF]`
- Existing helper/service remains authoritative during staging: `[YES/NO]`

## Identity and network evidence

- [ ] Gold and Paycheck each use an explicit absolute `upstream.binary` selected by the installer only when creating a new config.
- [ ] Existing `lan-mouse.pem` bytes are unchanged. Record SHA-256 hashes privately: Gold `[HASH]`; Paycheck `[HASH]`.
- [ ] Candidate `doctor --json` reports the selected PEM SHA-256. It does **not** claim a DTLS fingerprint unless separately observed from upstream.
- [ ] Reciprocal upstream DTLS fingerprints were observed from the actual candidate binaries and match the private allowlist: `[EVIDENCE_REF]`.
- [ ] Required backend/hook migration flags are present in `upstream.extra_args`: `[REDACTED_FLAG_NAMES/CONFIRMED]`.
- [ ] Trusted profile CIDR, exact gateway IP, interface (if configured), SSID (if configured), and gateway MAC (if configured) match live observations.
- [ ] Removing/unavailable SSID or gateway MAC causes the strict profile to fail closed.
- [ ] Peer address is inside the trusted CIDR. Overlay addresses are not used unless explicitly approved.
- [ ] Private-LAN firewall permits upstream UDP `[PORT]` in both directions and does not expose it on public profiles.

## SSH endpoint controls

- [ ] Dedicated key is in `known_hosts`-verified OpenSSH configuration; `BatchMode=yes` succeeds without prompts.
- [ ] `authorized_keys` uses `restrict,command="[ABSOLUTE_FORCED_COMMAND_WRAPPER ...]"` (or an equivalently audited restricted account).
- [ ] Wrapper accepts only fixed clipboard, screenshot export, and `endpoint status|on|off [EXPECTED_PEER_ID]` argv.
- [ ] `clipboard.endpoint_enabled` is true only on intended receivers.
- [ ] `remote_control.endpoint_enabled` is true only on intended remote-control receivers.
- [ ] Coordinator peer has `remote_control.enabled=true` and the reciprocal `remote_peer_id`.
- [ ] Remote ON test proves target-first, authoritative status read-back, then local start.
- [ ] Injected local-start failure proves remote OFF rollback and read-back.
- [ ] OFF test proves local stop, confirmed process exit, remote OFF, and read-back.

## Graphical and platform acceptance

- [ ] Linux GNOME Wayland login exposes `XDG_RUNTIME_DIR`, live `WAYLAND_DISPLAY`, and user D-Bus before upstream/clipboard attempts.
- [ ] Logout stops the graphical-session-bound user service; login is not delayed or held by readiness polling.
- [ ] macOS Accessibility and Input Monitoring permissions are granted to the selected upstream executable.
- [ ] macOS activation read-back shows both LaunchAgents and exactly one status process at the installed app path.
- [ ] Windows activation read-back shows the Scheduled Task's exact Python executable, arguments, least-privilege principal, and expected state.
- [ ] Windows native-machine path: private-profile firewall, OpenSSH, native clipboard Unicode, and login-task persistence verified.
- [ ] Windows VM path: bridged/private-LAN reachability and UDP verified. If SPICE clipboard is used, test it separately from the suite's OpenSSH clipboard path and record which layer owns synchronization.

## Functional cutover

- [ ] Stage mode left all new services/status jobs inactive until this point.
- [ ] Existing daemon configuration and helper state were backed up without mutation.
- [ ] `config validate`, `doctor --json`, and generated TOML review pass.
- [ ] Explicit activation read-back passes on each endpoint.
- [ ] Gold → Paycheck pointer and keyboard input passes; emergency release chord passes.
- [ ] Paycheck → Gold return path passes.
- [ ] Exact Unicode sentinel (privately recorded, includes non-ASCII and emoji) copies in both directions without loops or truncation.
- [ ] Optional remote clipboard SSH failure does not stop Gold's central Lan Mouse listener.
- [ ] Oversized screenshot is terminated/rejected; symlink export is rejected.
- [ ] Root-confined screenshot handoff succeeds in both directions without overwrite surprises.
- [ ] Final `status --json` reports local state from owned process identity and remote state as true/false only after authenticated read-back; unavailable remote state is `null`.

## Rollback

- [ ] Failed restart restores prior managed TOML and prior owned process.
- [ ] Ambiguous PID/process identity is never terminated; operator intervention path is documented.
- [ ] Deactivation commands were rehearsed. Original helpers/config/PEM remain available until post-cutover acceptance is signed.
- Acceptance owner/date: `[OWNER] / [UTC_DATE]`
