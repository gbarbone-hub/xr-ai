<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Offline startup fix for the model servers

Branch: `fix/offline-cached-model-startup`

## Summary

The model-server stack (`uv run main.py` / `uv run model_servers`) could not
start reliably without internet access, even when every model was already in
the local cache. The services contacted the Hugging Face Hub on each launch,
and nothing put them in offline mode.

This change makes the launcher detect an unreachable Hub and start every
service in Hugging Face offline mode, so cached models load directly.

## Root cause

1. **Host-process services (for example, Pocket TTS and STT).** At startup,
   `huggingface_hub` sends HEAD requests to resolve model revisions. When the
   Hub was unreachable, Pocket TTS retried with backoff for about 24 seconds
   before it fell back to the cache. Nothing set `HF_HUB_OFFLINE`.
2. **vLLM Docker services (Nemotron Omni, Cosmos VLM, embedding).** The
   container bootstrap in `utils/xr-ai-vllm/xr_ai_vllm/_docker.py` always ran
   these steps:
   - a `snapshot_download()` prefetch, which must reach the Hub to resolve the
     revision
   - an `hf-xet` check, which falls back to `pip install` when the check fails

   Also, `HF_HUB_OFFLINE` was not in the set of env vars forwarded into the
   container, so the container could not run offline even when the host set it.

## Fix

| File | Change |
|---|---|
| `utils/xr-ai-launcher/xr_ai_launcher/_offline.py` (new) | `configure_hf_offline()` makes a 3-second TCP probe to the Hub (it honors `HF_ENDPOINT`). If the probe fails, it sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` and logs a warning. An explicit `HF_HUB_OFFLINE` value (`0` or `1`) always wins, and no probe runs. The module uses only the standard library, as `AGENTS.md` requires for the launcher. |
| `utils/xr-ai-launcher/xr_ai_launcher/_stack.py` | `run_stack()` calls `configure_hf_offline()` right after `load_credentials()`. Child processes inherit the setting through `os.environ`. |
| `utils/xr-ai-vllm/xr_ai_vllm/_docker.py` | Forwards `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` into the container. When offline, it skips the `hf-xet` pip repair and the `snapshot_download` prefetch. vLLM then resolves the model ID to the local cache path. |
| `model-server-samples/model-servers/README.md` | Documents offline startup and the `HF_HUB_OFFLINE` override. |
| `tests/test_launcher_offline.py` (new) | Unit tests for the probe, the auto-enable path, the explicit overrides, and `HF_ENDPOINT` parsing. |
| `tests/test_vllm_docker.py` | Tests that offline mode forwards the flags and skips the Hub bootstrap, and that online mode keeps it. |
| `tests/test_launcher_stack.py` | Stubs `configure_hf_offline` so the `run_stack` unit tests make no network probe and leave no env state behind. |

## Usage

| Scenario | Behavior |
|---|---|
| Online (default) | Unchanged: one fast probe, and then normal Hub access. |
| No internet | The launcher logs `Hugging Face Hub is unreachable; starting in offline mode (cached models only)`, and all services load from `models/`. |
| Force offline | `HF_HUB_OFFLINE=1 uv run main.py` (no probe runs). |
| Force online | `HF_HUB_OFFLINE=0 uv run main.py` (no probe runs, and offline mode is never enabled). |

Prerequisite: run the stack online at least once, so that every model's weights
are in the repo `models/` cache.

## Validation (DGX Spark, GB10)

I simulated an unreachable Hub with `HF_ENDPOINT=http://127.0.0.1:9`.

| Run | Result |
|---|---|
| Online baseline | All 5 services ready (`stt`, `tts`, `omni`, `vlm`, `embedding`). |
| Hub unreachable, before the fix | Pocket TTS retried HEAD requests for about 24 s (8 attempts, `Connection refused`) before it fell back. The vLLM containers still went to the network, because the variable was not forwarded. |
| Hub unreachable, after the fix | The launcher auto-enabled offline mode. All 5 services were ready, and TTS was ready in 3 s. Each vLLM container logged `HF_HUB_OFFLINE is True, replace model_id [...] to model_path [.../models/hub/...]`. `docker inspect` showed `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. No Hub requests and no prefetch or pip steps ran. |

Unit tests: `test_launcher_offline.py`, `test_vllm_docker.py`,
`test_launcher_credentials.py`, and `test_launcher_stack.py`. All 144 tests
pass, and Ruff is clean.

## Notes and follow-ups

- When the offline flag changes, the vLLM container's launch fingerprint
  changes too. The first offline start (and the first start after you go back
  online) therefore recreates the containers instead of reusing the stopped
  ones.
- `extra_pip` still runs `pip install` inside the container even in offline
  mode. No current model-server YAML uses it, but a model that needs it would
  fail offline unless its image already includes the wheel.
- Running `uv run pytest` from `tests/` while the stack is up can hang on uv's
  cache lock. Run the tests after you stop the stack, or rely on CI.
