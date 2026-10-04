# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for xr_ai_launcher._offline (Hugging Face offline-mode detection)."""
from __future__ import annotations

import os

import pytest
import xr_ai_launcher._offline as _offline


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # setenv first so monkeypatch records the key and removes what the code under test writes.
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_ENDPOINT"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)


def test_unreachable_hub_enables_offline(monkeypatch):
    monkeypatch.setattr(_offline, "hub_reachable", lambda *a, **k: False)
    assert _offline.configure_hf_offline() is True
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_reachable_hub_stays_online(monkeypatch):
    monkeypatch.setattr(_offline, "hub_reachable", lambda *a, **k: True)
    assert _offline.configure_hf_offline() is False
    assert "HF_HUB_OFFLINE" not in os.environ


def test_explicit_offline_skips_probe(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    def _boom(*a, **k):
        raise AssertionError("must not probe when HF_HUB_OFFLINE is set")

    monkeypatch.setattr(_offline, "hub_reachable", _boom)
    assert _offline.configure_hf_offline() is True
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_explicit_online_overrides_probe(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setattr(_offline, "hub_reachable", lambda *a, **k: False)
    assert _offline.configure_hf_offline() is False
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert "TRANSFORMERS_OFFLINE" not in os.environ


def test_probe_uses_hf_endpoint(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "http://mirror.local:8080")
    assert _offline._hub_address() == ("mirror.local", 8080)


def test_probe_defaults_to_huggingface(monkeypatch):
    assert _offline._hub_address() == ("huggingface.co", 443)


def test_hub_reachable_false_on_connection_error(monkeypatch):
    def _refuse(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(_offline.socket, "create_connection", _refuse)
    assert _offline.hub_reachable() is False
