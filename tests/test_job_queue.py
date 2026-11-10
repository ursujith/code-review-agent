from app.jobs.queue import make_webhook_idempotency_key


def test_event_uuid_produces_stable_key():
    assert make_webhook_idempotency_key({}, "event-123") == make_webhook_idempotency_key(
        {"ignored": True}, "event-123"
    )


def test_fallback_key_changes_when_commit_changes():
    first = {
        "project": {"id": 7},
        "object_attributes": {
            "iid": 9,
            "action": "update",
            "state": "opened",
            "last_commit": {"id": "sha-a"},
        },
    }
    second = {
        "project": {"id": 7},
        "object_attributes": {
            "iid": 9,
            "action": "update",
            "state": "opened",
            "last_commit": {"id": "sha-b"},
        },
    }
    assert make_webhook_idempotency_key(first) != make_webhook_idempotency_key(second)
