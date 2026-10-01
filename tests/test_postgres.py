"""Opt-in PostgreSQL test. Uses an isolated schema, never existing tables."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from backend.app.db import Database, utcnow
from backend.app.jobs import enqueue, claim, touch, LeaseLost
from backend.app.models import Job, Config


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_jsonb_skip_locked_concurrent_queue_and_expired_lease():
    url = os.environ["TEST_DATABASE_URL"]
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as s:
        s.execute(text(f'CREATE SCHEMA "{schema}"'))
    # URL options are created structurally to avoid URL escaping pitfalls.
    test_url = admin.url.update_query_dict({"options": f"-csearch_path={schema}"})
    db = Database(test_url)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: db.initialize(), range(4)))
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(
                pool.map(
                    lambda _: enqueue(
                        db, "backtest", {"test": "日本株"}, {"engine": True}, "same-key"
                    ),
                    range(4),
                )
            )
        assert len(set(ids)) == 1
        for i in range(3):
            enqueue(db, "backtest", {"test": i}, {"engine": True})
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda _: claim(db), range(4)))
        assert all(claimed)
        assert len({x[0] for x in claimed}) == 4
        jid, owner = claimed[0]
        with db.session.begin() as s:
            s.get(Job, jid).lease_until = utcnow() - timedelta(seconds=1)
        retry_id, retry_owner = claim(db)
        assert retry_id == jid and retry_owner != owner
        with pytest.raises(LeaseLost):
            touch(db, jid, owner, status="completed")
        with db.session() as s:
            cfg = s.get(Config, ids[0])
            assert cfg.request == {"test": "日本株"}
            assert s.get(Job, jid).attempts == 2
    finally:
        db.engine.dispose()
        with admin.begin() as s:
            s.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
