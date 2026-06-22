import pytest

from clients.factory import create_client
from clients.openai_compatible_client import OpenAICompatibleClient


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class FakeHttpClient:
    def __init__(self):
        self.payload = None

    def post(self, url, json):
        self.payload = json
        return FakeResponse()

    def close(self):
        return None


def test_create_client_uses_unified_llm_config():
    client = create_client(
        {
            "base_url": "http://localhost:1234/v1",
            "api_key": "",
            "model": "local-model",
            "params": {"temperature": 0.2},
        }
    )

    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "http://localhost:1234/v1"
    assert client.model == "local-model"
    assert client.default_params == {"temperature": 0.2}
    client.close()


def test_empty_api_key_does_not_send_authorization_header():
    client = OpenAICompatibleClient(api_key="", model="local-model")

    assert "Authorization" not in client._client.headers
    client.close()


def test_api_key_sends_authorization_header():
    client = OpenAICompatibleClient(api_key="sk-test", model="online-model")

    assert client._client.headers["Authorization"] == "Bearer sk-test"
    client.close()


def test_default_params_are_sent_and_chat_kwargs_override_them():
    fake = FakeHttpClient()
    client = OpenAICompatibleClient(
        api_key="",
        model="local-model",
        default_params={"temperature": 0.2, "top_p": 0.8, "repeat_penalty": 1.1},
    )
    client._client = fake

    assert client.chat("hello", temperature=0.7) == "ok"
    assert fake.payload["temperature"] == 0.7
    assert fake.payload["top_p"] == 0.8
    assert fake.payload["repeat_penalty"] == 1.1
    client.close()


def test_unknown_chat_params_are_passed_through():
    fake = FakeHttpClient()
    client = OpenAICompatibleClient(api_key="", model="local-model")
    client._client = fake

    client.chat("hello", thinking={"type": "disabled"}, custom_flag=True)

    assert fake.payload["thinking"] == {"type": "disabled"}
    assert fake.payload["custom_flag"] is True
    client.close()


def test_factory_rejects_legacy_lmstudio_backend():
    with pytest.raises(ValueError, match="lmstudio 后端已移除"):
        create_client("lmstudio", {"url": "http://localhost:1234/v1"})
