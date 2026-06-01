from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import requests

from services.protocol import openai_v1_models


AUTH_KEY = "chatgpt2api"
BASE_URL = "http://localhost:8000"


class ModelListTests(unittest.TestCase):
    def test_list_models_falls_back_when_upstream_fails(self):
        with patch.object(openai_v1_models.OpenAIBackendAPI, "list_models", side_effect=RuntimeError("anon 401")):
            result = openai_v1_models.list_models()

        ids = {item["id"] for item in result["data"]}
        self.assertIn("auto", ids)
        self.assertIn("gpt-5", ids)
        self.assertIn("gpt-image-2", ids)
        self.assertIn("codex-gpt-image-2", ids)

    def test_list_models_function(self):
        """测试直接调用服务层获取模型列表。"""
        result = openai_v1_models.list_models()
        print("function result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    def test_list_models_http(self):
        """测试通过 HTTP 接口获取模型列表。"""
        response = requests.get(
            f"{BASE_URL}/v1/models",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            timeout=30,
        )
        print("http status:")
        print(response.status_code)
        print("http result:")
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
