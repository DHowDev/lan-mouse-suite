# LANBRIDGE: consolidate Mac/Titan controls in the existing suite

## User problem and result
Duplicate, confusing input/clipboard/audio controls make the Mac/Titan setup hard to operate. This change gives the existing suite window an OBS mixer panel and exposes it from the existing Mac status menu, with LANBRIDGE branding and compatibility-preserving identifiers.

## Boundaries
Local authenticated OBS only, dynamic user-owned source names, finite bounded gain, strict mute types, source rediscovery and write read-back. No arbitrary shell, output routing, drivers, remote mutations, recording resets, token storage or repository rename. Preserve the working Titan UDP5012 → Mac OBS monitored path and disabled UDP5013.

## Verification and limitations
Run compileall, full unittest discovery, and installer bash syntax checks. New adapter tests cover discovery, gain/mute/read-back, invalid inputs, missing auth and non-audio sources. These are injected-client tests, not live OBS evidence. Native Mac build/UI QA, real OBS authentication/read-back, Titan per-app control, and easy pairing bootstrap remain incomplete. Optional obsws-python and authenticated local OBS WebSocket setup are required; current supplied OBS setup has WebSocket disabled.

## Submission
Prepared locally only. GitHub auth was previously checked and unavailable per task context; no token hunt, push, remote PR or merge attempted. Submit only after authenticated access and target acceptance/review.
