<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Tea-making dashboard

Read-only presentation dashboard for the `tea-making-sample` agent: live camera, the
user/agent conversation, the current workflow step, and the models in use (highlighted as they fire).
A Clear button empties the transcript; it stays cleared across page reloads.

It does **not** modify or import the agent. It consumes:

- the sample's event viewer feed (`:8093`, proxied same-origin by `server.py`)
- the hub's camera track, joined as a subscribe-only LiveKit participant
  (`tea-making-dashboard`) via `https://localhost:8080/token`
- the sample's `yaml/workflow.yaml` and `yaml/models.local.json` (read-only)

## Run

Start the sample as usual (see the sample README), then from this directory:

```bash
uv sync
uv run server.py
# open http://<this-machine>:8095 (http://127.0.0.1:8095 locally)
```

The camera panel loads `livekit-client` from `client-samples/web-xr/vendor/` (built by
`client-samples/web-xr-build/build.sh`). The browser joins LiveKit on plain `ws://<host>:7880` (the server fetches the
token from the hub), so no certificate needs trusting. Rehearse with no stack: `uv run server.py --demo` (scripted
conversation, local webcam).

Options: `--port`, `--host`, `--events URL`, `--hub URL`, `--livekit-port N`. The server binds `0.0.0.0` by default so a laptop can reach a remote
development machine such as a Spark. The page and event feed (which carries
transcripts) are unauthenticated: use `--host 127.0.0.1` plus an SSH tunnel on
untrusted networks.
