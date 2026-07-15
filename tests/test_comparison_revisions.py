"""Persistence-boundary regressions for reproducible comparison lineups."""

from __future__ import annotations

import pytest

from ui.backend import session_store


PINNED_A = "a" * 40
PINNED_B = "B" * 40


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(session_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(session_store, "_DB_PATH", tmp_path / "sessions.db")
    session_store.init_db()
    return session_store


@pytest.mark.parametrize("revision", [None, "", "main", "release-v1", "abc123"])
def test_new_comparison_rejects_missing_or_mutable_revision(store, revision):
    with pytest.raises(ValueError, match="immutable Hugging Face commit revision"):
        store.create_session(
            title="Unpinned comparison",
            is_compare=True,
            models=[{"model_id": "org/model", "backend": "hf", "revision": revision}],
        )

    assert store.list_sessions() == []


def test_new_comparison_persists_normalized_commit_revisions(store):
    session = store.create_session(
        title="Pinned comparison",
        is_compare=True,
        models=[
            {"model_id": "org/a", "backend": "hf", "revision": PINNED_A},
            {"model_id": "org/b", "backend": "mlx", "revision": PINNED_B},
        ],
    )

    assert [model["revision"] for model in session["comparison_models"]] == [
        PINNED_A,
        PINNED_B.lower(),
    ]


def test_new_empty_comparison_cannot_later_accept_an_unpinned_lineup(store):
    session = store.create_session(title="Empty comparison", is_compare=True)

    with pytest.raises(ValueError, match="immutable Hugging Face commit revision"):
        store.set_comparison_models(session["id"], ["org/model"])

    assert store.get_comparison_models(session["id"]) == []


def test_historical_lineup_can_be_explicitly_migrated_and_forked(store):
    session = store.create_session(title="Legacy comparison", is_compare=True)
    store.add_message(session["id"], "user", "Compare these")
    store.add_message(session["id"], "assistant", "Alpha", model_id="org/alpha")
    store.add_message(session["id"], "assistant", "Beta", model_id="org/beta")

    before = store.get_session(session["id"])
    assert before["comparison_models"] == []
    assert before["models"] == ["org/alpha", "org/beta"]

    migrated = store.set_comparison_models(
        session["id"],
        ["org/alpha", {"model_id": "org/beta", "backend": "hf"}],
    )
    assert [model["model_id"] for model in migrated] == ["org/alpha", "org/beta"]
    assert [model["revision"] for model in migrated] == [None, None]

    restored = store.get_session(session["id"])
    assert restored["comparison_models"] == migrated
    forked = store.fork_session(session["id"], from_position=2)
    assert forked["comparison_models"] == [
        {**model, "session_id": forked["id"]} for model in migrated
    ]


def test_legacy_migration_cannot_replace_historical_model_identity(store):
    session = store.create_session(title="Legacy comparison", is_compare=True)
    store.add_message(session["id"], "assistant", "Alpha", model_id="org/alpha")
    store.add_message(session["id"], "assistant", "Beta", model_id="org/beta")

    with pytest.raises(ValueError, match="match its historical model IDs"):
        store.set_comparison_models(session["id"], ["org/alpha", "org/gamma"])

    assert store.get_comparison_models(session["id"]) == []
