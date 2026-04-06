"""Tests for topic storage operations."""

from datetime import datetime, timezone

from linkora.store import TopicStore, Topic, DocumentTopic


def _seed_workspace(tmp_db, workspace_id: str) -> None:
    conn = tmp_db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO workspaces (id, name, description, created_at, is_default) VALUES (?, ?, ?, ?, ?)",
        (
            workspace_id,
            workspace_id,
            "",
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            0,
        ),
    )
    conn.commit()


def test_topic_store_replace_and_list(tmp_db):
    workspace_id = "ws-topics"
    _seed_workspace(tmp_db, workspace_id)

    store = TopicStore(tmp_db)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    topics = [
        Topic(
            topic_id=1,
            workspace_id=workspace_id,
            label="alpha",
            top_terms=["alpha", "beta"],
            size=2,
            created_at=now,
        ),
        Topic(
            topic_id=2,
            workspace_id=workspace_id,
            label="gamma",
            top_terms=["gamma"],
            size=1,
            created_at=now,
        ),
    ]
    assignments = [
        DocumentTopic(doc_id="doc-1", workspace_id=workspace_id, topic_id=1, score=0.9),
        DocumentTopic(doc_id="doc-2", workspace_id=workspace_id, topic_id=2, score=0.8),
    ]

    store.replace_workspace(workspace_id, topics, assignments)

    listed = store.list_topics(workspace_id)
    assert [t.topic_id for t in listed] == [1, 2]
    assert listed[0].top_terms == ["alpha", "beta"]

    listed_assignments = store.list_assignments(workspace_id)
    assert len(listed_assignments) == 2


def test_topic_store_replace_clears_previous(tmp_db):
    workspace_id = "ws-replace"
    _seed_workspace(tmp_db, workspace_id)

    store = TopicStore(tmp_db)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    store.replace_workspace(
        workspace_id,
        [
            Topic(
                topic_id=1,
                workspace_id=workspace_id,
                label="alpha",
                top_terms=["alpha"],
                size=1,
                created_at=now,
            )
        ],
        [
            DocumentTopic(
                doc_id="doc-1", workspace_id=workspace_id, topic_id=1, score=0.5
            )
        ],
    )

    store.replace_workspace(
        workspace_id,
        [
            Topic(
                topic_id=2,
                workspace_id=workspace_id,
                label="beta",
                top_terms=["beta"],
                size=1,
                created_at=now,
            )
        ],
        [
            DocumentTopic(
                doc_id="doc-2", workspace_id=workspace_id, topic_id=2, score=0.7
            )
        ],
    )

    listed = store.list_topics(workspace_id)
    assert [t.topic_id for t in listed] == [2]
    listed_assignments = store.list_assignments(workspace_id)
    assert [a.doc_id for a in listed_assignments] == ["doc-2"]
