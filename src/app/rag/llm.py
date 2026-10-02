from dataclasses import dataclass


class LLMProvider:
    def answer(self, prompt: str) -> str:
        raise NotImplementedError


@dataclass(slots=True)
class MockLLM(LLMProvider):
    response: str = "I don't have access to information that answers this."

    def answer(self, prompt: str) -> str:
        return self.response
