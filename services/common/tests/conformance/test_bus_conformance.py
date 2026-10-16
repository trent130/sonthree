"""Shared behavior suite for current and future EventBus implementations."""

from receipts_common.bus import LocalEventBus


def test_bus_preserves_per_key_publish_order_and_offsets():
    bus = LocalEventBus()
    expected = [
        bus.publish("events", "match-a", {"sequence": sequence})
        for sequence in range(4)
    ]
    reader = bus.subscribe("events", "order-check")
    actual = [reader.poll(timeout=0) for _ in expected]

    assert [record.offset for record in actual] == [0, 1, 2, 3]
    assert [record.doc for record in actual] == [{"sequence": n} for n in range(4)]
    assert [record.key for record in actual] == ["match-a"] * 4
    assert [record.offset for record in expected] == [0, 1, 2, 3]


def test_consumer_group_resumes_after_last_committed_offset():
    bus = LocalEventBus()
    for sequence in range(3):
        bus.publish("claims", "match-a", {"sequence": sequence})

    first_process = bus.subscribe("claims", "durable-group")
    assert first_process.poll(timeout=0).doc == {"sequence": 0}
    committed = first_process.poll(timeout=0)
    first_process.commit(committed.offset)

    restarted_process = bus.subscribe("claims", "durable-group", from_offset=0)
    assert restarted_process.poll(timeout=0).doc == {"sequence": 2}
