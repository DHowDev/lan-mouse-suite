# Native mixer review

The existing menu item opens an AppKit NSPanel, not Tk. Sources are discovered dynamically from local OBS; each audio source has volume and mute controls. Reads run off the main thread; slider writes debounce for 300 ms, serialize, and read back through the existing backend. Failed requests disable controls and show setup instructions.

Build with `bash apps/macos/build-app.sh`. Launch an isolated mixer using `bash scripts/launch-mixer-macos.sh`. Set LANBRIDGE_MIXER_VENV to an isolated Python 3.9+ venv containing this package and obsws-python. No Tk dependency or legacy GUI changes. The launcher inherits the hidden password in the process environment, not arguments or repository files. LANBRIDGE_MIXER_APP can select an isolated app build.

OBS setup is manual: Tools → WebSocket Server Settings → enable server on loopback port 4455 and authentication. Previously inspected Mac configuration had authentication enabled but the server disabled. No settings, audio, recording, Lan Mouse services, output selection, or running menu app are changed by this review.

Mac review checkout: /Users/mac/lanbridge-reviews/mixer-7db9113-1789275138.
Current native build and offline smoke results: verification-native.txt (created by this review run). Live source/control verification remains gated on the user enabling OBS WebSocket. Legacy Tk suite UI is unchanged.

Existing screenshot/config path fixes are retained. Commit and PR publication are deferred to the requested next phase after test review.
