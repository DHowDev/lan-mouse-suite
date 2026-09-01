# Lan Mouse Suite

Lan Mouse Suite is a small, standard-library Python companion for [upstream Lan Mouse](https://github.com/feschber/lan-mouse). It provides trusted-LAN detection, process ownership, a portable control window, a native macOS status item, bidirectional UTF-8 clipboard sync over OpenSSH, and an optional safe screenshot-path inbox.

**Upstream Lan Mouse is still the mouse/keyboard engine. Upstream Lan Mouse does not provide clipboard sync; this suite supplies the clipboard layer.** No upstream binaries, private keys, certificate identities, host fingerprints, personal hostnames, or personal LAN addresses are vendored here.

## Supported matrix

| Platform | Network adapter | Clipboard adapter | UI | Autostart |
|---|---|---|---|---|
| Arch Linux, Wayland | `ip -j route` / `ip -j addr` | `wl-paste` / `wl-copy` | Tk | systemd user + desktop autostart |
| Ubuntu, Wayland | `ip -j route` / `ip -j addr` | `wl-paste` / `wl-copy` | Tk | systemd user + desktop autostart |
| macOS | `route -n get default` / `ipconfig` | `pbpaste` / `pbcopy` | Tk + AppKit status item source | launchd |
| Windows 10/11 | fixed PowerShell `Get-NetRoute` / `Get-NetIPAddress` | fixed PowerShell `Get-Clipboard` / `Set-Clipboard` | Tk | Scheduled Task + Startup folder |

Python 3.9 or newer is supported, including Apple Python 3.9.6 when it can create a `venv`. The package has no runtime Python dependencies.

## Architecture

```text
Tk UI / macOS status item
          |
     lanmouse-suite CLI (JSON status and actions)
          |
  trusted-LAN guard ------ platform adapter
          |                       |
  generated minimal TOML     routes + clipboard
          |
  one tracked upstream lan-mouse process

clipboard sync: local adapter <-> ssh peer "lanmouse-suite clipboard read|write"
screenshot pull: local CLI <-> ssh peer "lanmouse-suite screenshot export --request-stdin"
```

Focused modules live under `src/lanmouse_suite/`: configuration/paths, OS adapters, network matching, TOML rendering, owned-process orchestration, clipboard state machine, screenshot validation, service loop, CLI, and Tk GUI. Commands are always argv arrays with `shell=False`. Clipboard text and screenshot paths are never interpolated into a remote command.

## Clean install

Clone or unpack this repository locally. Review the installer before running it. Installers copy this local package into a private venv using the standard library only; setuptools, wheel, build isolation, and network access are not required. They never download-and-execute a remote script. **Every installer stages by default:** it installs files, templates, and a new config, but does not enable/start the service, Scheduled Task, status app, or Startup item. Activation is a separate `--activate` / `-Activate` cutover with state read-back.

### Arch Linux

```sh
./install-linux.sh --system-deps
```

The Arch branch uses `sudo pacman` only for system packages (`python`, `tk`, `wl-clipboard`, OpenSSH, and separately packaged `lan-mouse`). Without `--system-deps`, no `sudo` is used. After editing config and reviewing `doctor --json`, activate with `./install-linux.sh --activate`. The Ubuntu installer uses the same explicit activation flag.

### Ubuntu

```sh
./install-linux.sh --system-deps
```

The Ubuntu branch installs Python/Tk/Wayland clipboard/OpenSSH packages with `apt`; install upstream Lan Mouse separately. For an explicit release asset:

```sh
./install-linux.sh \
  --upstream-url 'https://example.invalid/path/to/lan-mouse' \
  --upstream-sha256 'PUBLISHER_VERIFIED_64_HEX_SHA256'
```

The URL must be HTTPS and a checksum is mandatory. This explicit downloader accepts a raw Linux ELF only, rejects ZIP/non-ELF payloads, verifies it, then installs it; no downloaded script is executed. macOS app bundles and Windows ZIP/MSI assets must use a publisher-supported platform-native installer instead.

### macOS

```sh
./install-macos.sh
```

This uses any local Python 3.9+, including Apple Python 3.9.6, to create `~/.local/share/lanmouse-suite/venv`. If that Python cannot create a venv, the installer stops rather than fetching code. With Apple Command Line Tools available, it atomically compiles and ad-hoc signs `~/Applications/Lan Mouse Suite.app`. `./install-macos.sh --activate` loads separate service and status-app LaunchAgents, reads both back, and requires exactly one status process at the installed path. Quit keeps the status item closed until next login/manual job start. Upstream Lan Mouse remains separately installed.

### Windows / Windows VM

From a regular PowerShell (administrator is not required for the suite):

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1
```

Python 3.9+ and the Windows OpenSSH Client are prerequisites. The installer selects `py -3` first and verifies >=3.9. Install upstream Lan Mouse separately with its publisher-supported package. `.\install-windows.ps1 -Activate` checks every native exit code, creates the least-privilege Scheduled Task and Startup entry, then reads back the exact task action, arguments, and state.

**Native Windows path:** verify private-profile UDP/firewall scope, OpenSSH, native `Get-Clipboard`/`Set-Clipboard` Unicode fidelity, and login-task persistence.

**Windows VM path:** use bridged networking when possible; otherwise use an explicit private network/static address. NAT commonly prevents peer-initiated UDP and mDNS. SPICE clipboard is a separate hypervisor path: test it separately from this suite's OpenSSH clipboard and assign one layer ownership so two bidirectional loops are never active.

## Configure

Platform-native JSON locations:

- Linux: `${XDG_CONFIG_HOME:-~/.config}/lanmouse-suite/config.json`
- macOS: `~/Library/Application Support/LanMouseSuite/config.json`
- Windows: `%APPDATA%\LanMouseSuite\config.json`

The installer copies `examples/config.example.json` only when no config exists, disables clipboard by default, and writes persistent manual OFF before enabling the background service. Replace every example address, name, SSH target, and all-zero placeholder fingerprint, then explicitly turn on a peer. Validate:

```sh
lanmouse-suite config validate
lanmouse-suite status --json
```

Each trusted profile binds a CIDR to its exact default gateway and, optionally, interface, SSID, and gateway MAC. Linux reads SSID/gateway neighbor identity with `iw`/`ip neigh`, macOS uses Wi-Fi/route/ARP tools, and Windows uses `netsh`/PowerShell. If a profile configures `ssid` or `gateway_mac`, an unavailable or unequal observation fails closed. Peer mDNS/static addresses are accepted only inside the matched CIDR; `tailscale_addresses` remain ignored unless explicitly opted in.

`peer.port` is the upstream Lan Mouse UDP port. The separate TCP `peer.probe_port` (normally SSH 22) is informational management reachability only. Local startup depends on trusted local-network identity and a bounded graphical-session check—not peer TCP liveness—so a sleeping peer or failed optional clipboard SSH probe never stops the central listener.

`upstream.binary` is resolved to a canonical executable path before launch. Optional `upstream.cert_path` is passed explicitly as `--cert-path`; `upstream.extra_args` preserves required backend/hook flags and normally ends in `daemon`. Installers discover an existing absolute binary only for a newly created config and never rewrite an existing selection.

## Pairing and SSH prerequisites

1. Install and run compatible upstream Lan Mouse on both devices.
2. Authorize each sending device's real Lan Mouse DTLS certificate fingerprint on the receiver.
3. Put those fingerprint-to-label mappings in `upstream.authorized_fingerprints`.
4. Configure native OpenSSH public-key authentication in `peer.ssh.target`; `BatchMode=yes` is enforced.
5. Enable `clipboard.endpoint_enabled` only on intended clipboard receivers. `clipboard.enabled` controls the polling coordinator separately.
6. For coordinated power state, set `remote_control.endpoint_enabled=true` only on the endpoint host, and set the coordinator peer's `remote_control.enabled=true` plus reciprocal `remote_peer_id`. ON is target-first/status-read-back/local-second with remote rollback if local startup fails; OFF is local-first/confirmed-exit/remote-off/read-back. Endpoint handlers suppress further remote coordination, preventing recursion.
7. Restrict the key. The repository includes `scripts/ssh-forced-command.py`, which allowlists only exact clipboard read/write, screenshot export, and `endpoint status|on|off EXPECTED_PEER_ID` commands. A representative `authorized_keys` prefix is:

   ```text
   restrict,command="/ABS/PYTHON /ABS/ssh-forced-command.py --cli /ABS/lanmouse-suite --peer-id EXPECTED_LOCAL_PEER" ssh-ed25519 REDACTED_PUBLIC_KEY
   ```

   Use absolute paths and a dedicated key/account; verify the installed platform's `authorized_keys` supports `restrict`.

Host-key verification uses normal OpenSSH configuration and `known_hosts`; the suite never accepts host keys automatically. The optional identity file is one argv value. All remote control/status argv are fixed; if authenticated status is unavailable, UI `remote_on` is `null`/unknown and is never copied from local state.

## Permissions

- **macOS:** grant upstream Lan Mouse Accessibility and Input Monitoring. `pbpaste`/`pbcopy` run in the logged-in GUI session. The AppKit status item only invokes the packaged CLI.
- **Linux Wayland:** install `wl-clipboard`; the user service discovers the logged-in user's live `wayland-*` socket when systemd did not import `WAYLAND_DISPLAY`, and supplies `XDG_RUNTIME_DIR` and the user D-Bus address to the managed Lan Mouse child. It is bound to `graphical-session.target`, not `default.target`, so it cannot hold stale graphical-session state across logout. GNOME/KDE may request Remote Desktop Portal permission for upstream Lan Mouse. Wlroots compositors need their supported capture/emulation backend.
- **Windows:** run in an interactive desktop session. Enable the OpenSSH Client, and OpenSSH Server when the VM/device is a remote clipboard endpoint. Upstream Lan Mouse may require a private-network firewall exception.

## Operation

```sh
lanmouse-suite status --json
lanmouse-suite on PEER_ID
lanmouse-suite all-off
lanmouse-suite guard --json
lanmouse-suite service once
lanmouse-suite gui
```

The macOS menu-bar app polls `status --json` every few seconds with a bounded (15 s) CLI timeout. If a poll fails it keeps the last known device list and shows a "status stale, retrying…" banner instead of a dead "Status unavailable" menu; a hung CLI process is terminated so the app never freezes in a busy state.

Manual OFF is persisted separately from transient guard failures. A trusted-network recovery never clears it. One cross-process lock serializes service/UI/CLI control and process state. Process ownership requires canonical executable path, exact argv with one exact managed `--config` relationship, and persisted creation identity (`/proc` NUL argv/start ticks on Linux; executable/creation time plus defensively parsed command line on macOS/Windows). Ambiguity refuses termination. Stop waits for confirmed exit; failed replacement restores the prior managed config and process.

### Clipboard

Clipboard sync is UTF-8 text only, size-capped, and bidirectional:

```sh
lanmouse-suite clipboard sync PEER_ID --once
```

The state machine records only SHA-256 hashes after a successful delivery (or after observing both sides already equal). Failed deliveries are retried. Simultaneous edits use the configured deterministic conflict winner. Logs contain direction and byte count only—never clipboard text, private key data, or clipboard hashes.

### Optional screenshot path inbox

Enable screenshots and set absolute `inbox_root` and `export_root` paths independently on each endpoint. Pull a known remote path:

```sh
lanmouse-suite screenshot pull PEER_ID '/configured/export/root/capture.png' --copy-path
```

The remote path is sent as JSON on stdin to a fixed SSH command, not interpolated. SSH stdout is read by a bounded streaming runner that buffers at most `max_bytes+1` payload bytes and terminates overflow. On POSIX, export traversal opens each component root-relative with no-follow flags, then validates/reads the already-open regular-file descriptor; symlinks are refused. Windows screenshot export currently fails closed because safe junction/reparse-point traversal needs a native handle implementation; Windows clipboard sync remains supported. The receiver uses a safe leaf and atomic root-confined write; an identical basename intentionally replaces the previous inbox copy atomically.

## Safe migration from an ad-hoc setup

1. Run the platform installer **without** activation. Leave the existing daemon/helpers authoritative and do not delete or disable them.
2. Back up the existing upstream config directory, including PEM/certificate identity files, and privately record their SHA-256 hashes.
3. Create/edit suite JSON with every peer/profile and required migration input. Preserve non-default capture/emulation/enter-hook choices in `upstream.extra_args`; do not assume the minimal generated TOML can infer every historical behavior.
4. Import without modifying the source:

   ```sh
   lanmouse-suite config import-lan-mouse ~/.config/lan-mouse/config.toml
   ```

   The import preserves authorization mappings, selects an explicit TOML `cert_path` or sibling `lan-mouse.pem` when present, imports recognized backend/hook flags into `upstream.extra_args`, records the source path, and writes future managed TOML beside it. It never writes the source TOML or PEM.
5. Run `config validate` and `doctor --json`. Doctor verifies the selected executable/version probe, config hash, explicit PEM SHA-256 (hash only; it reports the DTLS fingerprint as not computed), graphical environment, configured SSH endpoints, and screenshot roots without clipboard/key content.
6. Review generated TOML and compare the actual candidate upstream fingerprint separately. Do not claim identity continuity from a PEM hash alone.
7. Use [the redacted Gold/Paycheck acceptance template](docs/deployment-acceptance-template.md), then invoke the explicit platform activation flag. Keep old helpers/config until pointer, keyboard, UTF-8 clipboard, screenshot, login persistence, and rollback checks pass.

The uninstallers preserve config by default and never touch upstream Lan Mouse or its identity. Pass `--purge-config` (Unix) or `-PurgeConfig` (Windows) only when intentionally removing suite configuration.

## Security model

- Trust requires exact CIDR + gateway (+ configured interface/SSID/gateway MAC); configured strong observations fail closed when unavailable.
- No embedded personal infrastructure or credentials.
- All subprocesses use argv arrays and `shell=False`; SSH endpoint verbs are fixed and a forced-command allowlist is supplied.
- Clipboard polling and receiving are separate strict booleans; UTF-8 size/poll/backoff limits are validated.
- Screenshot SSH capture is bounded to `max_bytes+1`; POSIX export is descriptor-based/no-follow; Windows export fails closed; imports are atomic.
- Manual OFF survives recovery; the Linux graphical-session unit uses bounded environment readiness without peer-liveness coupling.
- Only an exact executable/argv/config/creation identity is terminated, under one cross-process lock with confirmed exit and restart rollback.
- Authenticated remote status alone produces `remote_on=true/false`; failure is unknown (`null`).

Network identity is a safety gate, not cryptographic authentication. Lan Mouse certificate authorization and SSH host/user authentication remain required.

## Development and checks

No test mutates the live clipboard.

```sh
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build --no-isolation   # when the local build module is available
bash -n install-linux.sh install-macos.sh uninstall-linux.sh uninstall-macos.sh apps/macos/build-app.sh
```

PowerShell scripts are syntax-checked when `pwsh` is available. The Python source is also parsed against Python 3.9 grammar in the test suite.
