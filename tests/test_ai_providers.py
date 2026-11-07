"""AI providers: platform default, Company override, OpenAI and local OpenAI-compatible models (no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.providers.factory import choose_ai  # noqa: E402
from reckon_sales_agent.providers.llm import (  # noqa: E402
    LLMError,
    OpenAICompatibleProvider,
    blocks_account,
    parse_json,
)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
PLATFORM = {"ai_provider": "Anthropic (Claude)", "ai_model": "claude-opus-5-5", "openai_model": "gpt-x",
            "local_ai_model": "qwen2.5:14b", "local_ai_base_url": "http://127.0.0.1:11434/v1"}


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body
        self.text = json.dumps(body)

    def json(self):
        return self.body


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def answer(content, finish="stop", **message):
    return Response(200, {"choices": [{"message": {"content": content, **message}, "finish_reason": finish}]})


class ChooseAITests(unittest.TestCase):
    def test_platform_default_applies_to_every_company(self):
        setup = choose_ai(PLATFORM, {"company": "Acme"})
        self.assertEqual((setup["kind"], setup["model"], setup["source"]), ("anthropic", "claude-opus-5-5", "platform"))
        self.assertEqual((setup["scope"], setup["error"]), ("platform:anthropic", ""))
        local = choose_ai({**PLATFORM, "ai_provider": "Local (OpenAI-compatible)"}, {"company": "Acme"})
        self.assertEqual((local["kind"], local["base_url"], local["model"]),
                         ("local", "http://127.0.0.1:11434/v1", "qwen2.5:14b"))

    def test_company_override_only_when_the_vendor_allows_it(self):
        company = {"company": "Acme", "ai_provider_override": "OpenAI", "ai_model_override": "gpt-mini"}
        self.assertEqual(choose_ai(PLATFORM, company)["kind"], "anthropic")
        setup = choose_ai({**PLATFORM, "allow_company_ai_override": 1}, company)
        self.assertEqual((setup["kind"], setup["model"], setup["source"]), ("openai", "gpt-mini", "company"))
        self.assertEqual((setup["key_from"], setup["scope"]), ("platform", "platform:openai"))

    def test_company_key_pauses_only_that_company(self):
        company = {"company": "Acme", "ai_provider_override": "OpenAI", "has_api_key_override": True}
        setup = choose_ai({**PLATFORM, "allow_company_ai_override": 1}, company)
        self.assertEqual((setup["key_from"], setup["scope"], setup["model"]), ("company", "company:Acme", "gpt-x"))

    def test_company_endpoint_needs_permission_and_https(self):
        company = {"company": "Acme", "ai_provider_override": "Local (OpenAI-compatible)",
                   "ai_base_url_override": "https://ai.acme.example/v1"}
        allowed = {**PLATFORM, "allow_company_ai_override": 1}
        self.assertIn("does not allow", choose_ai(allowed, company)["error"])
        setup = choose_ai({**allowed, "allow_company_ai_endpoints": 1}, company)
        self.assertEqual((setup["base_url"], setup["custom_endpoint"], setup["scope"], setup["error"]),
                         ("https://ai.acme.example/v1", True, "company:Acme", ""))
        plain = choose_ai({**allowed, "allow_company_ai_endpoints": 1},
                          {**company, "ai_base_url_override": "http://10.0.0.5/v1"})
        self.assertIn("HTTPS", plain["error"])

    def test_missing_model_or_address_is_reported(self):
        self.assertIn("No model", choose_ai({"ai_provider": "OpenAI"}, {"company": "Acme"})["error"])
        local = choose_ai({"ai_provider": "Local (OpenAI-compatible)", "local_ai_model": "m"}, {"company": "Acme"})
        self.assertIn("No address", local["error"])

    def test_unknown_provider_falls_back_to_claude(self):
        self.assertEqual(choose_ai({"ai_provider": "Gemini"}, {"company": "Acme"})["kind"], "anthropic")


class OpenAICompatibleTests(unittest.TestCase):
    def test_openai_sends_a_strict_schema(self):
        session = Session(answer('{"ok": true}'))
        llm = OpenAICompatibleProvider("sk-test", "gpt-x", session=session)
        self.assertEqual(llm.complete_json("sys", "user", SCHEMA, max_tokens=50), {"ok": True})
        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/chat/completions")
        self.assertTrue(call["json"]["response_format"]["json_schema"]["strict"])
        self.assertEqual(call["json"]["max_completion_tokens"], 50)
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test")

    def test_local_server_falls_back_to_json_mode(self):
        session = Session(Response(400, {"error": {"message": "response_format json_schema unsupported"}}),
                          answer('```json\n{"ok": false}\n```'))
        llm = OpenAICompatibleProvider(None, "qwen", "http://127.0.0.1:11434/v1/", kind="local",
                                       scope="platform:local", session=session)
        self.assertEqual(llm.complete_json("sys", "user", SCHEMA), {"ok": False})
        self.assertEqual(session.calls[0]["url"], "http://127.0.0.1:11434/v1/chat/completions")
        retry = session.calls[1]["json"]
        self.assertEqual(retry["response_format"], {"type": "json_object"})
        self.assertIn('"required"', retry["messages"][0]["content"])
        self.assertIn("max_tokens", retry)
        self.assertNotIn("Authorization", session.calls[0]["headers"])  # a local server without a key

    def test_errors_carry_the_providers_reason(self):
        session = Session(Response(429, {"error": {"message": "You exceeded your current quota"}}))
        with self.assertRaises(LLMError) as caught:
            OpenAICompatibleProvider("k", "gpt-x", session=session).complete_json("s", "u", SCHEMA)
        self.assertIn("no credit left", str(caught.exception))  # plain words for the person using the app
        self.assertIn("quota", caught.exception.detail)  # the provider's own reason stays for logs and administrators
        self.assertTrue(blocks_account(429, "You exceeded your current quota, check your billing"))
        self.assertFalse(blocks_account(429, "Rate limit reached for requests"))

    def test_refusal_and_cut_off_answers_fail(self):
        refused = Session(answer(None, refusal="no"))
        with self.assertRaisesRegex(LLMError, "declined"):
            OpenAICompatibleProvider("k", "m", session=refused).complete_json("s", "u", SCHEMA)
        cut = Session(answer('{"ok"', finish="length"))
        with self.assertRaisesRegex(LLMError, "cut off"):
            OpenAICompatibleProvider("k", "m", session=cut).complete_json("s", "u", SCHEMA)


class ParseJsonTests(unittest.TestCase):
    def test_tolerates_text_around_the_object(self):
        self.assertEqual(parse_json('Here you go: {"a": 1} done'), {"a": 1})
        with self.assertRaises(LLMError):
            parse_json("[1, 2]")
        with self.assertRaises(LLMError):
            parse_json("no json")


class SettingsFieldTests(unittest.TestCase):
    def test_settings_have_the_provider_fields(self):
        doctypes = Path(__file__).parents[1] / "reckon_sales_agent" / "reckon_sales_agent" / "doctype"
        expected = {
            "sales_agent_platform_settings": ["ai_provider", "openai_api_key", "local_ai_base_url",
                                              "allow_company_ai_override", "allow_company_ai_endpoints"],
            "sales_agent_settings": ["ai_provider_override", "ai_model_override", "ai_api_key_override",
                                     "ai_base_url_override"],
        }
        for folder, names in expected.items():
            doc = json.loads((doctypes / folder / f"{folder}.json").read_text(encoding="utf-8"))
            fields = {f["fieldname"]: f for f in doc["fields"]}
            for name in names:
                self.assertIn(name, fields)
                self.assertIn(name, doc["field_order"])
        # Keys are stored encrypted, never as plain text.
        platform = json.loads((doctypes / "sales_agent_platform_settings" /
                               "sales_agent_platform_settings.json").read_text(encoding="utf-8"))
        kinds = {f["fieldname"]: f["fieldtype"] for f in platform["fields"]}
        self.assertEqual((kinds["openai_api_key"], kinds["local_ai_api_key"]), ("Password", "Password"))


if __name__ == "__main__":
    unittest.main()
