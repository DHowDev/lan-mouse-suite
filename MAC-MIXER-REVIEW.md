# Draft review: Mac OBS / Titan mixer

Scope: existing Titan stream into Mac OBS. No output routing, Titan per-app controls, recording operations or server configuration writes.

## Setup
For a new installation, run `bash install-macos.sh` without `--activate`. Do not reinstall over a live repair installation merely to review this branch. After installation, run `bash scripts/launch-mixer-macos.sh`. It checks Tk, installs the optional OBS client into the installer's venv, prompts for the password without echo/persistence, and opens the existing suite controls. Existing installations must contain this branch's mixer code.

In OBS choose Tools → WebSocket Server Settings. Manually enable the server and authentication on port 4455, then use that password in the launcher. Refresh OBS sources in the LANBRIDGE panel. A disabled server is not a successful connection. Do not restart OBS or disturb an active recording to review this change.

## Actual target-Mac verification
Isolated checkout: `/Users/mac/lanbridge-reviews/mixer-7db9113-1789275138`.
Native `apps/macos/build-app.sh`: compiled with Swift 6.2.4, signed and signature-verified. This project builds with swiftc, not a Swift Package.swift manifest.
Apple Python 3.9 isolated venv: Tk 8.5 and obsws-python import successfully. Editable install required upgrading the venv's old pip; after upgrade installation succeeded.
Full pytest: 54 passed, 2 skipped, 2 failed. Failures: test_config_toml path equality and test_screenshots absolute export path handling with macOS /var versus /private/var aliases. These remain unresolved; review is not all-green. Screenshot security behavior was not relaxed as a shortcut.
Read-only OBS configuration: server_enabled=false, auth_required=true, server_port=4455. Loopback connection refused (61). No live mixer connection or audio-control test claimed. No visible GUI launch or recording changes performed.

## Publication
No GitHub credential discovered in the additional checked gateway gh hosts metadata, git credential helper, or standard profile.env GitHub key names. No push or PR created. An already-authenticated authorized GitHub context is needed. Configured GitHub MCP inspection remains incomplete. Keep this as draft-review material, not merge-ready.
