"""Viz HTTP access token and path containment."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from brainkm.services.viz import _VizHandler, start_viz_server


def test_viz_api_requires_token() -> None:
    handle = start_viz_server(
        project_dir=None,
        port=0,
        open_browser=False,
        demo=True,
    )
    try:
        base = f"http://127.0.0.1:{handle.port}"
        try:
            urllib.request.urlopen(f"{base}/api/graph", timeout=2)  # noqa: S310
            raise AssertionError("expected HTTP 401 without token")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        token = _VizHandler.access_token
        with urllib.request.urlopen(  # noqa: S310
            f"{base}/api/version?token={token}",
            timeout=2,
        ) as resp:
            body = json.loads(resp.read().decode())
            assert "node_count" in body
            assert body["node_count"] >= 1
    finally:
        handle.stop()


def test_webllm_base_uses_bound_port_not_host(monkeypatch) -> None:
    _VizHandler.bound_port = 5999
    _VizHandler.project_dir = None
    _VizHandler.access_token = "tok"

    monkeypatch.setattr(
        "brainkm.services.webllm_prefetch.is_model_cached",
        lambda _mid: True,
    )
    monkeypatch.setattr(
        "brainkm.services.webllm_prefetch.webllm_engine_config",
        lambda mid, local_model_base_url="": {
            "model": local_model_base_url,
            "model_id": mid,
        },
    )
    monkeypatch.setattr(
        "brainkm.services.webllm_prefetch.model_lib_url",
        lambda _mid: "http://example/lib",
    )
    monkeypatch.setattr(
        "brainkm.services.webllm_prefetch.status_summary",
        lambda _mid: {"models": []},
    )

    handler = _VizHandler.__new__(_VizHandler)
    cfg = handler._webllm_config()
    model_url = cfg["app_config"]["model_list"][0]["model"]
    assert model_url.startswith("http://127.0.0.1:5999/models/")
    assert "evil.example" not in model_url
