from __future__ import annotations


def test_list_agents(client) -> None:
    r = client.get("/api/v1/agents")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert names == {"generalist", "extractor"}


def test_get_generalist_spec(client) -> None:
    r = client.get("/api/v1/agents/generalist")
    assert r.status_code == 200
    spec = r.json()
    assert spec["name"] == "generalist"
    assert spec["output_type"] == "string"
    assert "calculator" in spec["tools"]
    assert "delegate_skill" in spec["tools"]
    assert spec["capabilities"] == ["thinking"]
    assert spec["uses_memory"] is True
    assert spec["instructions_key"] == "generalist"
    assert spec["default_max_steps"] == 16


def test_get_extractor_schema(client) -> None:
    r = client.get("/api/v1/agents/extractor")
    assert r.status_code == 200
    spec = r.json()
    assert spec["output_type"] == "structured_output"
    assert spec["output_schema"]["title"] == "ExtractionResult"
    assert spec["uses_memory"] is False
    assert spec["tools"] == []


def test_get_agent_404(client) -> None:
    r = client.get("/api/v1/agents/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "agent_not_found"
