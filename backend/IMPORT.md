# Backend source import

Imported from `git@github.com:Rehan-shah/dubhacks-backend.git`, branch `main`,
at commit `18128eb60fd0e80fc3b97fd128681ae30ef2368b`.

This directory contains the upstream tracked files, including its shipped
models and sample outputs. It is a source snapshot, without a nested `.git`
directory. Existing frontend, coaching, and Photon files remain at the project
root. `npm run imessage-video-server` now invokes the imported coaching pipeline
through the root upload harness for iMessage videos. The other app entry points
retain their existing pipelines.

Run upstream commands from this directory; see [the backend README](README.md)
and [the coaching prototype setup](coaching/README.md). The viewer's default
port 8000 overlaps with our existing upload service, so run one at a time or
configure another port.

The parent repository's ignore rules still exclude some imported models,
videos, and generated/sample outputs from ordinary Git staging. They are
present locally. No dependencies were installed or services started during
this import.
