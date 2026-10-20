import uuid
from pathlib import Path

import pytest

from app.engine import Engine
from app.store import Store


@pytest.fixture
def data_dir():
    # Regular inherited Windows ACLs; tempfile's private ACLs conflict with the
    # restricted Windows runner. Each test still receives an isolated database.
    path = Path(__file__).resolve().parent.parent / ".cache" / "tests" / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture
def store(data_dir):
    return Store(data_dir)


@pytest.fixture
def engine(store):
    engine = Engine(store)
    store.set_setting("credentials", {"api_id": 12345, "api_hash": "a" * 32})
    for index, account in enumerate(["alpha", "beta"]):
        store.execute("INSERT INTO accounts(id,label,phone,user_id,status) VALUES (?,?,?,?,'connected')",
                      (account, account, f"+1555000000{index}", 9000+index))
    return engine
