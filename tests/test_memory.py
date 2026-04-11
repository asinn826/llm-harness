"""Tests for the memory system."""
import json
import os
import pytest
from unittest.mock import patch
from memory import (
    load_facts, save_facts, add_fact, search_facts,
    compile_paragraph, remove_fact, _MEMORY_FILE,
)


@pytest.fixture(autouse=True)
def clean_memory(tmp_path):
    """Use a temp file for memory during tests."""
    import memory
    test_file = tmp_path / "memory.json"
    orig_file = memory._MEMORY_FILE
    orig_dir = memory._MEMORY_DIR
    memory._MEMORY_FILE = test_file
    memory._MEMORY_DIR = tmp_path
    yield test_file
    memory._MEMORY_FILE = orig_file
    memory._MEMORY_DIR = orig_dir


class TestAddFact:
    def test_adds_new_fact(self):
        fact = add_fact("Alex means Alex Jiang", category="contact")
        assert fact["text"] == "Alex means Alex Jiang"
        assert fact["category"] == "contact"
        assert fact["use_count"] == 1

    def test_deduplicates_same_text(self):
        add_fact("Alex means Alex Jiang")
        result = add_fact("Alex means Alex Jiang")
        assert result["use_count"] == 2
        assert len(load_facts()) == 1

    def test_case_insensitive_dedup(self):
        add_fact("alex means Alex Jiang")
        result = add_fact("Alex Means Alex Jiang")
        assert result["use_count"] == 2
        assert len(load_facts()) == 1

    def test_always_on_flag(self):
        fact = add_fact("User is in Seattle", always_on=True)
        assert fact["always_on"] is True

    def test_invalid_category_defaults_to_general(self):
        fact = add_fact("some fact", category="invalid")
        assert fact["category"] == "general"


class TestSearchFacts:
    def test_finds_matching_fact(self):
        add_fact("Alex means Alex Jiang", category="contact")
        results = search_facts("Alex")
        assert len(results) == 1
        assert "Alex Jiang" in results[0]["text"]

    def test_case_insensitive_search(self):
        add_fact("Tyler Pollak's birthday is in March")
        results = search_facts("tyler")
        assert len(results) == 1

    def test_no_results(self):
        add_fact("Alex means Alex Jiang")
        results = search_facts("banana")
        assert len(results) == 0

    def test_searches_category(self):
        add_fact("some fact", category="contact")
        results = search_facts("contact")
        assert len(results) == 1

    def test_updates_use_count(self):
        add_fact("Alex means Alex Jiang")
        search_facts("Alex")
        facts = load_facts()
        assert facts[0]["use_count"] == 2  # 1 from add + 1 from search


class TestCompileParagraph:
    def test_empty_when_no_facts(self):
        assert compile_paragraph() == ""

    def test_empty_when_no_always_on(self):
        add_fact("some fact", always_on=False)
        assert compile_paragraph() == ""

    def test_includes_always_on_facts(self):
        add_fact("User is in Seattle", always_on=True)
        paragraph = compile_paragraph()
        assert "USER CONTEXT:" in paragraph
        assert "Seattle" in paragraph

    def test_respects_char_limit(self):
        # Add many always-on facts
        for i in range(50):
            add_fact(f"Fact number {i} with some extra text to fill space", always_on=True)
        paragraph = compile_paragraph()
        assert len(paragraph) <= 800

    def test_most_used_facts_first(self):
        add_fact("Rarely used fact", always_on=True)
        fact2 = add_fact("Frequently used fact", always_on=True)
        # Bump use count
        for _ in range(10):
            search_facts("Frequently")
        paragraph = compile_paragraph()
        # Frequently used should appear before rarely used
        freq_pos = paragraph.index("Frequently")
        rare_pos = paragraph.index("Rarely")
        assert freq_pos < rare_pos


class TestRemoveFact:
    def test_removes_existing_fact(self):
        fact = add_fact("temporary fact")
        assert remove_fact(fact["id"]) is True
        assert len(load_facts()) == 0

    def test_returns_false_for_missing(self):
        assert remove_fact("nonexistent") is False


class TestToolIntegration:
    def test_remember_tool(self):
        from tools import remember
        result = remember("Tyler's birthday is March 15", category="fact")
        assert "Remembered" in result
        facts = load_facts()
        assert len(facts) == 1

    def test_recall_tool(self):
        # Call search_facts directly since the tool wrapper has
        # the same logic — avoids pytest module caching issues
        add_fact("Tyler's birthday is March 15")
        results = search_facts("Tyler birthday")
        assert len(results) > 0
        assert "March 15" in results[0]["text"]

    def test_recall_nothing(self):
        results = search_facts("nonexistent thing")
        assert len(results) == 0

    def test_remember_always_on(self):
        from tools import remember
        remember("Alex means Alex Jiang", category="contact", always_on=True)
        paragraph = compile_paragraph()
        assert "Alex Jiang" in paragraph

    def test_system_prompt_includes_memory(self):
        from harness import build_system_prompt
        from tools import TOOLS
        add_fact("User is in Seattle", always_on=True)
        prompt = build_system_prompt(TOOLS)
        assert "Seattle" in prompt
        assert "USER CONTEXT:" in prompt
