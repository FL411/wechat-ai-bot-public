import importlib

import yaml


def _write_persona(persona_dir, name, identity="identity", setting="setting"):
    path = persona_dir / name
    path.mkdir()
    (path / "identity.txt").write_text(identity, encoding="utf-8")
    (path / "persona.md").write_text(setting, encoding="utf-8")
    return path


def test_config_update_deep_merges_visible_sections(tmp_path, monkeypatch):
    appmod = importlib.import_module("web_console.app")
    config_file = tmp_path / "bot_config.yaml"
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    config_file.write_text(
        yaml.safe_dump(
            {
                "prompt": {"max_total_chars": 1000, "hidden": "keep"},
                "search": {
                    "enabled": False,
                    "hidden": "keep",
                    "tavily": {"api_key": "secret", "hidden": "keep"},
                },
                "persona": {"persona_dir": str(persona_dir), "active": "base"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(appmod, "CONFIG_FILE", str(config_file))

    client = appmod.app.test_client()
    response = client.post(
        "/api/config",
        json={"prompt": {"max_total_chars": 2000}, "search": {"tavily": {"max_results": 3}}},
    )

    assert response.status_code == 200
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert config["prompt"]["max_total_chars"] == 2000
    assert config["prompt"]["hidden"] == "keep"
    assert config["search"]["hidden"] == "keep"
    assert config["search"]["tavily"]["api_key"] == "secret"
    assert config["search"]["tavily"]["hidden"] == "keep"
    assert config["search"]["tavily"]["max_results"] == 3


def test_config_update_blank_secret_values_keep_existing_keys(tmp_path, monkeypatch):
    appmod = importlib.import_module("web_console.app")
    config_file = tmp_path / "bot_config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "llm": {"api_key": "existing-llm-key", "model": "old-model"},
                "search": {"tavily": {"api_key": "existing-tavily-key", "max_results": 5}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(appmod, "CONFIG_FILE", str(config_file))

    client = appmod.app.test_client()
    response = client.post(
        "/api/config",
        json={
            "llm": {"api_key": "", "model": "new-model"},
            "search": {"tavily": {"api_key": "   ", "max_results": 3}},
        },
    )

    assert response.status_code == 200
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert config["llm"]["api_key"] == "existing-llm-key"
    assert config["llm"]["model"] == "new-model"
    assert config["search"]["tavily"]["api_key"] == "existing-tavily-key"
    assert config["search"]["tavily"]["max_results"] == 3


def test_persona_crud_and_active_delete_switch(tmp_path, monkeypatch):
    appmod = importlib.import_module("web_console.app")
    config_file = tmp_path / "bot_config.yaml"
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    _write_persona(persona_dir, "base", "base identity", "base setting")
    config_file.write_text(
        yaml.safe_dump(
            {"persona": {"persona_dir": str(persona_dir), "active": "base"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(appmod, "CONFIG_FILE", str(config_file))

    client = appmod.app.test_client()

    response = client.post(
        "/api/personas",
        json={"name": "new_role", "identity": "id", "setting": "set"},
    )
    assert response.status_code == 200
    assert (persona_dir / "new_role" / "identity.txt").read_text(encoding="utf-8") == "id"

    assert client.post("/api/personas", json={"name": "../bad"}).status_code == 400
    assert client.post("/api/personas", json={"name": "new_role"}).status_code == 400

    response = client.post(
        "/api/persona/new_role",
        json={"identity": "id2", "setting": "set2"},
    )
    assert response.status_code == 200
    assert (persona_dir / "new_role" / "persona.md").read_text(encoding="utf-8") == "set2"

    response = client.post("/api/persona/new_role/activate")
    assert response.status_code == 200
    assert (
        yaml.safe_load(config_file.read_text(encoding="utf-8"))["persona"]["active"] == "new_role"
    )

    response = client.post("/api/persona/new_role/copy", json={"name": "copy_role"})
    assert response.status_code == 200
    assert (persona_dir / "copy_role" / "identity.txt").read_text(encoding="utf-8") == "id2"

    response = client.delete("/api/persona/new_role")
    assert response.status_code == 200
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert config["persona"]["active"] in {"base", "copy_role"}
    assert not (persona_dir / "new_role").exists()


def test_delete_only_persona_is_rejected(tmp_path, monkeypatch):
    appmod = importlib.import_module("web_console.app")
    config_file = tmp_path / "bot_config.yaml"
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    _write_persona(persona_dir, "only")
    config_file.write_text(
        yaml.safe_dump(
            {"persona": {"persona_dir": str(persona_dir), "active": "only"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(appmod, "CONFIG_FILE", str(config_file))

    client = appmod.app.test_client()
    response = client.delete("/api/persona/only")

    assert response.status_code == 400
    assert (persona_dir / "only").exists()
