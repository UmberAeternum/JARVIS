# Release checklist - 3.29.0 (2026-11-07)

## Built
- [ ] Smoke suite green (release.py refuses to build otherwise)
- [ ] UNSIGNED build - configure UMBRA_SIGN_CERT and re-run with --sign before wide distribution
- [ ] jarvis_ai-3.29.0-py3-none-any.whl built
- [ ] UMBRA.exe built
- [ ] SHA256SUMS matches the artifacts (`sha256sum -c dist/SHA256SUMS`)
- [ ] Wheel secret scan clean (release.py enforces)

## Publish
- [ ] Commit with the version bump (title has NO version number)
- [ ] Tag v3.29.0 and push it
- [ ] GitHub release: attach wheel, UMBRA.exe (if built), SHA256SUMS
- [ ] Sign the update manifest (payload + Ed25519 signature) and upload
      umbra-manifest.json to the release - the update checker reads it
- [ ] CI green on the release commit
- [ ] Storefront (docs/index.html) copy reflects the new features
- [ ] NO private key material anywhere: Documents/umbra-private and
      PRIVATE-DO-NOT-SHARE stay out of every artifact and upload
- [ ] Update the launcher repo release if the Android app changed
