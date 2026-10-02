import re


_CITATION = re.compile(r"\[([A-Za-z0-9_-]+)\]")


def guard_output(answer: str, allowed_chunk_ids: set[str]) -> str:
    """Remove citations that were not present in the verified prompt context."""
    return _CITATION.sub(lambda match: match.group(0) if match.group(1) in allowed_chunk_ids else "", answer).strip()
