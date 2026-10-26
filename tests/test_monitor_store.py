import pytest

from monitor_store import MonitorStore, NotFoundError, ValidationError


@pytest.fixture
def store(tmp_path):
    return MonitorStore(tmp_path / "db" / "monitors.sqlite")


@pytest.fixture
def payload():
    return dict(origin="tpe", destination="nrt", depart_start="2027-03-01",
                depart_end="2027-03-15", return_start="2027-03-06",
                return_end="2027-03-22", min_stay=5, max_stay=7,
                airlines=["JL", "BR"], cabin="economy", down_threshold=500)


def test_crud_and_persistence(store, payload, tmp_path):
    item = store.create("alice", payload)
    assert item["origin"] == "TPE" and item["airlines"] == ["BR", "JL"]
    assert len(MonitorStore(tmp_path / "db" / "monitors.sqlite").list("alice")) == 1
    updated = store.update("alice", item["id"], {"enabled": False, "target_price": 9000})
    assert updated["enabled"] is False and updated["target_price"] == 9000
    store.delete("alice", item["id"])
    assert store.list("alice") == []


def test_strict_owner_isolation(store, payload):
    item = store.create("alice", payload)
    assert store.list("bob") == []
    with pytest.raises(NotFoundError):
        store.get("bob", item["id"])
    with pytest.raises(NotFoundError):
        store.update("bob", item["id"], {"target_price": 1})
    with pytest.raises(NotFoundError):
        store.delete("bob", item["id"])
    assert store.get("alice", item["id"])["enabled"]


@pytest.mark.parametrize("patch", [
    {"origin": "123"}, {"destination": "TPE"},
    {"depart_end": "2027-02-28"}, {"return_end": None},
    {"min_stay": 9}, {"down_threshold": -1},
    {"airlines": ["XX"]}, {"enabled": "false"},
    {"owner_id": "bob"}, {"cabin": "spaceship"},
])
def test_invalid_input(store, payload, patch):
    with pytest.raises(ValidationError):
        store.create("alice", {**payload, **patch})


def test_missing_owner(store, payload):
    with pytest.raises(ValidationError):
        store.create("", payload)
