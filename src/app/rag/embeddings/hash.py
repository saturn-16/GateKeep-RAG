import hashlib
import math


class HashEmbeddingProvider:
    """Deterministic local embedding used for zero-credit development and tests."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in text.lower().split():
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % self.dimensions
            values[index] += 1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]
