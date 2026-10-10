# presentation-view

Read-only presentation page for the `tea-making-sample` agent: live camera, the
user/agent conversation, the current workflow step, and the models in use (highlighted as they fire).
A Clear button empties the transcript; it stays cleared across page reloads.

It does **not** modify or import the agent. It consumes:

- the sample's event viewer feed (`:8092`, proxied same-origin by `server.py`)
- the hub's camera track, joined as a subscribe-only LiveKit participant
  (`presentation-view`) via `https://localhost:8080/token`
- the sample's `yaml/workflow.yaml` and `yaml/models.local.json` (read-only)

## Run

Start the stack as usual, then from this directory:

```bash
uv sync
uv run server.py
# open http://127.0.0.1:8095
```

The browser joins LiveKit on plain `ws://<host>:7880` (the server fetches the
token from the hub), so no certificate needs trusting. Rehearse with no stack: `uv run server.py --demo` (scripted
conversation, local webcam).

Options: `--port`, `--host`, `--events URL`, `--hub URL`, `--livekit-port N`. For a remote machine
use an SSH tunnel for `8095` (the event feed carries transcripts).
