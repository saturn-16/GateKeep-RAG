"""Seed the deterministic in-process demo dataset."""

from app.api.state import state

print(f"Demo state ready: {len(state.users)} users, {len(state.retriever._chunks)} ACL'd chunks")
