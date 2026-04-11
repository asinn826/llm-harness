"""Persistent memory: facts the model learns about the user across sessions.

Storage: ~/.llm_harness/memory.json
Two access patterns:
  - Always-on paragraph: top facts injected into every system prompt (~200 tokens)
  - On-demand recall: model calls recall() tool to search the full store
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

_MEMORY_DIR = Path.home() / ".llm_harness"
_MEMORY_FILE = _MEMORY_DIR / "memory.json"
_MAX_PARAGRAPH_CHARS = 800  # ~200 tokens

VALID_CATEGORIES = {"contact", "preference", "fact", "correction", "general"}


def _ensure_dir():
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def load_facts() -> list[dict]:
    """Load all facts from disk."""
    if not _MEMORY_FILE.exists():
        return []
    try:
        with open(_MEMORY_FILE) as f:
            data = json.load(f)
        return data.get("facts", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_facts(facts: list[dict]):
    """Save all facts to disk."""
    _ensure_dir()
    with open(_MEMORY_FILE, "w") as f:
        json.dump({"facts": facts}, f, indent=2)


def add_fact(text: str, category: str = "general", always_on: bool = False) -> dict:
    """Add a new fact to memory. Returns the created fact."""
    if category not in VALID_CATEGORIES:
        category = "general"

    facts = load_facts()

    # Check for duplicates (same text, case-insensitive)
    for existing in facts:
        if existing["text"].lower().strip() == text.lower().strip():
            existing["last_used"] = datetime.now().strftime("%Y-%m-%d")
            existing["use_count"] = existing.get("use_count", 0) + 1
            save_facts(facts)
            return existing

    fact = {
        "id": str(uuid.uuid4())[:8],
        "category": category,
        "text": text.strip(),
        "created": datetime.now().strftime("%Y-%m-%d"),
        "last_used": datetime.now().strftime("%Y-%m-%d"),
        "use_count": 1,
        "always_on": always_on,
    }
    facts.append(fact)
    save_facts(facts)
    return fact


def search_facts(query: str) -> list[dict]:
    """Search facts by keyword matching. All query words must appear in the fact."""
    facts = load_facts()
    query_words = query.lower().split()
    results = []
    for fact in facts:
        text_lower = fact["text"].lower()
        cat_lower = fact.get("category", "").lower()
        if all(w in text_lower or w in cat_lower for w in query_words):
            fact["last_used"] = datetime.now().strftime("%Y-%m-%d")
            fact["use_count"] = fact.get("use_count", 0) + 1
            results.append(fact)
    if results:
        save_facts(facts)  # update use counts
    return results


def compile_paragraph() -> str:
    """Build the always-on memory paragraph for the system prompt.

    Returns an empty string if no always-on facts exist.
    Caps at ~200 tokens (~800 chars) to keep context budget bounded.
    """
    facts = load_facts()
    always_on = [f for f in facts if f.get("always_on")]
    if not always_on:
        return ""

    # Most-used facts first
    always_on.sort(key=lambda f: f.get("use_count", 0), reverse=True)

    lines = [f["text"] for f in always_on]
    paragraph = "USER CONTEXT: " + " ".join(lines)

    if len(paragraph) > _MAX_PARAGRAPH_CHARS:
        # Trim to fit, dropping least-used facts from the end
        paragraph = "USER CONTEXT: "
        for line in lines:
            if len(paragraph) + len(line) + 1 > _MAX_PARAGRAPH_CHARS:
                break
            paragraph += line + " "
        paragraph = paragraph.strip()

    return paragraph


def remove_fact(fact_id: str) -> bool:
    """Remove a fact by ID. Returns True if found and removed."""
    facts = load_facts()
    original_len = len(facts)
    facts = [f for f in facts if f.get("id") != fact_id]
    if len(facts) < original_len:
        save_facts(facts)
        return True
    return False
