from dataclasses import dataclass
import json
from urllib.request import Request, urlopen


class LLMProvider:
    def answer(self, prompt: str) -> str:
        raise NotImplementedError


@dataclass(slots=True)
class MockLLM(LLMProvider):
    response: str = "I don't have access to information that answers this."

    def answer(self, prompt: str) -> str:
        return self.response


@dataclass(slots=True)
class OllamaLLM(LLMProvider):
    model: str = "qwen2.5:7b"
    url: str = "http://localhost:11434/api/generate"

    def answer(self, prompt: str) -> str:
        request = Request(self.url, data=json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=120) as response:
            payload = json.loads(response.read())
        return str(payload.get("response", "I don't have access to information that answers this."))
