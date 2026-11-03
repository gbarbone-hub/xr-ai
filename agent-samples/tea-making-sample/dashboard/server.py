#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Presentation dashboard server for the tea-making sample.

Serves the static page, proxies the sample's read-only event feed
(same-origin, so no CORS needed), and exposes the workflow steps and model
roster read from the sample's own config files. Never writes to xr-ai.

    python3 server.py                 # live: events from http://127.0.0.1:8093
    python3 server.py --demo          # scripted events, no stack required
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
SAMPLE = HERE.parent
# livekit-client is the build output of client-samples/web-xr-build/build.sh,
# shared with the web client instead of being copied into this app.
VENDOR = HERE.parents[2] / "client-samples/web-xr/vendor"

# Friendly names for adapter presets / roles shown on the models panel.
PRESET_LABELS = {
    "nemotron_omni": "Nemotron-3 Nano Omni",
    "parakeet_stt": "Parakeet STT",
    "pocket_tts": "Pocket TTS",
    "nemotron_embedding": "Nemotron Embedding",
}
ROLE_LABELS = {
    "llm": ("LLM", "Reasoning, tool calls, step judging"),
    "vlm": ("VLM", "Describes what the camera sees"),
    "stt": ("Speech-to-text", "Transcribes the user"),
    "tts": ("Text-to-speech", "Speaks the agent's replies"),
    "embedding": ("Embeddings", "Retrieval over tea documents"),
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


def load_steps(sample: Path) -> tuple[list[dict], str]:
    # Step ids are fixed by the worker's flow sequence (tea_sop_agent._STEP_IDS).
    titles = {
        "identify": "Identify the tea",
        "fill_water": "Fill the heating vessel",
        "heat_water": "Heat the water",
        "start_steeping": "Start steeping",
        "steep_timer": "Steep",
    }
    return [{"id": k, "title": v} for k, v in titles.items()], "Tea making"

    data = yaml.safe_load((sample / "yaml/workflow.yaml").read_text())
    return [{"id": s["id"], "title": s.get("title", s["id"])} for s in data["steps"]], data["task"]["name"]


def load_models(sample: Path) -> list[dict]:
    try:
        cfg = json.loads((sample / "yaml/models.local.json").read_text())["models"]
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for role, spec in cfg.items():
        adapter, endpoint = spec.get("adapter", {}), spec.get("endpoint", {})
        name = PRESET_LABELS.get(
            adapter.get("preset", ""), adapter.get("model_name") or adapter.get("preset") or role
        )
        if role == "vlm":  # shares the omni endpoint; show the model actually behind it
            name = next(
                (
                    PRESET_LABELS.get(s.get("adapter", {}).get("preset", ""))
                    for s in cfg.values()
                    if s.get("endpoint") == endpoint and s.get("adapter", {}).get("preset") in PRESET_LABELS
                ),
                name,
            )
        label, purpose = ROLE_LABELS.get(role, (role, ""))
        out.append(
            {
                "role": role,
                "label": label,
                "purpose": purpose,
                "model": name,
                "endpoint": endpoint.get("base_url", ""),
            }
        )
    order = list(ROLE_LABELS)
    return sorted(out, key=lambda m: order.index(m["role"]) if m["role"] in order else 99)


class Demo:
    """Scripted event timeline so the page can be rehearsed without the stack."""

    SCRIPT = [
        (1, "participant.lifecycle", {"event": "joined"}),
        (2, "guidance.events", {"event": "participant.joined", "message": ""}),
        (
            4,
            "foreground",
            {
                "query": "Agent, start making tea.",
                "response": "Great, let's make tea. First, show me the front of the tea box.",
                "tools": ["workflow__start"],
            },
        ),
        (
            4.2,
            "guidance.events",
            {"event": "step.enter", "step_id": "identify", "message": "Show me the tea box label."},
        ),
        (
            9,
            "background.video-log",
            {"text": "A person holds a green box of Earl Grey tea toward the camera."},
        ),
        (
            12,
            "guidance.events",
            {"event": "step.commit", "step_id": "identify", "message": "Tea: Earl Grey, 100 C, 3 min."},
        ),
        (
            12.5,
            "guidance.events",
            {"event": "step.enter", "step_id": "fill_water", "message": "Fill the kettle with water."},
        ),
        (
            14,
            "foreground",
            {
                "query": "How much water should I use?",
                "response": "About one cup per serving, so roughly 240 milliliters.",
                "tools": ["rag__search"],
            },
        ),
        (
            20,
            "guidance.events",
            {"event": "step.commit", "step_id": "fill_water", "message": "Water is visible in the kettle."},
        ),
        (
            20.5,
            "guidance.events",
            {"event": "step.enter", "step_id": "heat_water", "message": "Turn the kettle on."},
        ),
        (26, "background.change-watch", {"text": "Kettle indicator light turned on."}),
        (
            28,
            "guidance.events",
            {"event": "step.enter", "step_id": "start_steeping", "message": "Add the tea bag."},
        ),
        (
            34,
            "guidance.events",
            {"event": "step.enter", "step_id": "steep_timer", "message": "Steeping for 3 minutes."},
        ),
        (
            38,
            "guidance.events",
            {"event": "workflow.complete", "message": "Tea guidance complete. Enjoy your tea."},
        ),
    ]

    def __init__(self) -> None:
        self.t0 = time.time()

    def after(self, after: int) -> dict:
        elapsed = time.time() - self.t0
        due = [(i + 1, e) for i, e in enumerate(self.SCRIPT) if e[0] <= elapsed]
        events = [
            {
                "sequence": n,
                "topic": t,
                "participant_id": "demo",
                "timestamp_us": int((self.t0 + at) * 1e6),
                "payload": {**p, "timestamp_us": int((self.t0 + at) * 1e6)},
            }
            for n, (at, t, p) in due
            if n > after
        ]
        return {"events": events, "cursor": len(due), "oldest": 1, "reset": False}


def make_handler(args: argparse.Namespace):
    steps, task = load_steps(SAMPLE)
    config = {"task": task, "steps": steps, "models": load_models(SAMPLE), "hub": args.hub, "demo": args.demo}
    demo = Demo() if args.demo else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            req = urlparse(self.path)
            if req.path == "/api/config":
                return self._send(json.dumps(config).encode(), "application/json")
            if req.path == "/api/livekit":
                # The hub's token endpoint uses a self-signed cert the browser may not trust, so
                # fetch the token here and point the browser at LiveKit's plain ws port instead.
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
                    with urllib.request.urlopen(
                        f"{args.hub}/token?identity=tea-making-dashboard", timeout=5, context=ctx
                    ) as r:
                        token = json.load(r)["token"]
                except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                    return self._send(
                        json.dumps({"error": f"hub token request failed: {e}"}).encode(),
                        "application/json",
                        HTTPStatus.BAD_GATEWAY,
                    )
                host = (
                    (self.headers.get("Host") or "localhost").rsplit(":", 1)[0]
                    if not (self.headers.get("Host") or "").startswith("[")
                    else "localhost"
                )
                return self._send(
                    json.dumps({"token": token, "url": f"ws://{host}:{args.livekit_port}"}).encode(),
                    "application/json",
                )
            if req.path == "/api/events":
                after = int(parse_qs(req.query).get("after", ["0"])[0] or 0)
                if demo:
                    return self._send(json.dumps(demo.after(after)).encode(), "application/json")
                try:
                    with urllib.request.urlopen(f"{args.events}/api/events?after={after}", timeout=3) as r:
                        return self._send(r.read(), "application/json")
                except (urllib.error.URLError, OSError):
                    return self._send(
                        b'{"error":"event feed unreachable"}', "application/json", HTTPStatus.BAD_GATEWAY
                    )
            name = "index.html" if req.path == "/" else req.path.lstrip("/")
            root, name = (
                (VENDOR, name.removeprefix("vendor/")) if name.startswith("vendor/") else (STATIC, name)
            )
            path = (root / name).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                return self._send(b"not found", "text/plain", HTTPStatus.NOT_FOUND)
            self._send(path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

    return Handler


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8095)
    p.add_argument(
        "--host", default="0.0.0.0",
        help="bind address; the default serves the LAN so a laptop can reach a remote dev box",
    )
    p.add_argument("--events", default="http://127.0.0.1:8093", help="sample event viewer base URL")
    p.add_argument("--hub", default="https://localhost:8080", help="device-io-hub base URL (token + LiveKit)")
    p.add_argument("--livekit-port", type=int, default=7880, help="LiveKit plain ws port on the hub host")
    p.add_argument("--demo", action="store_true", help="serve scripted events instead of the live feed")
    args = p.parse_args()
    if not (VENDOR / "livekit-client.esm.mjs").is_file():
        print(
            f"note: {VENDOR}/livekit-client.esm.mjs is missing, so the camera panel "
            "will not load; run client-samples/web-xr-build/build.sh (the webcam button still works)"
        )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args))
    print(
        f"tea-making dashboard → http://{args.host}:{args.port}  ({'demo' if args.demo else 'live: ' + args.events})"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
