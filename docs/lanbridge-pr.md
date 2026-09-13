# LANBRIDGE: native Mac panel for Mac/Titan OBS audio

## Summary
- Add a native AppKit NSPanel opened from the existing Mac status menu, with an isolated `--mixer-only` launcher. The legacy Tk suite window remains separate and unchanged by the native implementation.
- Discover local OBS audio inputs supporting volume/mute; provide named gain (0–1) and mute controls, background reads, debounced slider writes, source rediscovery and read-back. Failed requests disable native controls and display setup guidance.
- Support the existing Titan stream as one input in Mac OBS and Mac capture/microphone/media inputs that OBS exposes with volume/mute support. This is not Mac system volume, remote Titan control or Titan per-app discovery.
- Retain macOS lexical/canonical path fixes without relaxing descriptor-relative no-follow screenshot validation.

## Setup and boundaries
Build with `bash apps/macos/build-app.sh`. Use a Python 3.9+ venv containing this package and optional `obsws-python>=1.7,<2`; select it with `LANBRIDGE_MIXER_VENV`, then run `bash scripts/launch-mixer-macos.sh`. `LANBRIDGE_MIXER_APP` selects an isolated app build. No Tk is required for this native panel.

Manually enable OBS WebSocket authentication on port 4455 and restrict network access to loopback before live review. Enabling the server alone does not guarantee a loopback-only listener. The client endpoint is fixed to `127.0.0.1:4455`. The launcher prompts without echo and inherits the password through the environment, never arguments or repository files; the status-menu app also needs that launching environment. The supplied deployment previously had the server disabled and authentication enabled.

No output routing, monitoring changes, drivers, recording operations, OBS configuration writes, service restarts, remote audio mutations, repository rename or merge. Preserve the existing Titan UDP5012 → Mac OBS monitored path and disabled UDP5013.

## Verification
- Supplied target-Mac `verification-native.txt`: 61 tests run, 2 skipped, no failures; native offline-panel smoke reports disabled controls/setup guidance.
- Implementation review reported native Swift compilation/ad-hoc signing; PR preparation independently rechecked the built Mac app signature successfully. The supplied text log itself contains tests/offline smoke, not a compiler transcript.
- Adapter/bridge tests use injected clients. Current PR preparation reruns the full existing unittest suite, compileall, shell syntax and diff whitespace checks; final results are in the separate review report.

## Limitations
The supplied live verification confirms native mixer launch and authenticated localhost OBS discovery/read access, with audio, mute, monitoring and recording state unchanged. Live volume/mute writes were not tested; audible behavior after control changes and end-to-end UI interaction remain unverified. Offline smoke does not establish visual/UI interaction quality. No Titan per-app controls, output routing or one-click pairing bootstrap.

## Submission
This document is the proposed PR body, not a publication receipt. The separate PR-phase review report records the actual commit, push and PR outcome. No merge is authorized.
