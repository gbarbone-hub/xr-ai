# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hugging Face offline-mode detection for the launcher.

With the Hub unreachable, every ``from_pretrained`` / ``snapshot_download`` call
retries with backoff and then fails (or stalls startup) even when the weights
are already cached. Setting ``HF_HUB_OFFLINE=1`` makes those calls resolve from
the local cache only, and child processes inherit it through ``os.environ``.
"""

from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 3.0
_TRUTHY = {"1", "ON", "YES", "TRUE"}


def hf_offline_requested(env: dict[str, str] | None = None) -> bool:
    """True when ``HF_HUB_OFFLINE`` is set to a truthy value in *env*."""
    env = os.environ if env is None else env
    return env.get("HF_HUB_OFFLINE", "").strip().upper() in _TRUTHY


def _hub_address() -> tuple[str, int]:
    parsed = urlparse(os.environ.get("HF_ENDPOINT") or "https://huggingface.co")
    port = parsed.port or (80 if parsed.scheme == "http" else 443)
    return parsed.hostname or "huggingface.co", port


def hub_reachable(timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """True when a TCP connection to the Hugging Face Hub succeeds."""
    try:
        with socket.create_connection(_hub_address(), timeout=timeout):
            return True
    except OSError:
        return False


def configure_hf_offline() -> bool:
    """Enable Hugging Face offline mode when asked to or when the Hub is down.

    An explicit ``HF_HUB_OFFLINE`` value (``0`` or ``1``) always wins and is
    never probed. Returns whether offline mode is active.
    """
    if "HF_HUB_OFFLINE" in os.environ:
        offline = hf_offline_requested()
    else:
        offline = not hub_reachable()
        if offline:
            log.warning(
                "Hugging Face Hub is unreachable; starting in offline mode "
                "(cached models only). Set HF_HUB_OFFLINE=0 to disable."
            )

    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return offline
