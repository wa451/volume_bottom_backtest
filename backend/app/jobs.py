from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.utils import fingerprint
from .db import utcnow
from .models import Job, Config

ACTIVE = ("downloading", "preprocessing", "backtesting", "analyzing")


def enqueue(db, kind, request, engine_config, key=None):
    if key is not None and (not key or len(key) > 128):
        raise HTTPException(400, "Idempotency-Keyは1〜128文字です")
    digest = fingerprint({"kind": kind, "request": request})
    with db.session.begin() as s:
        if key:
            old = s.scalar(select(Job).where(Job.idempotency_key == key))
            if old:
                if old.request_hash != digest:
                    raise HTTPException(409, "同じキーで異なる設定は登録できません")
                return old.id
        job_id = str(uuid4())
        s.add(Job(id=job_id, kind=kind, idempotency_key=key, request_hash=digest))
        try:
            s.flush()
            s.add(Config(job_id=job_id, request=request, engine_config=engine_config))
        except IntegrityError:
            s.rollback()
            with db.session() as retry:
                old = retry.scalar(select(Job).where(Job.idempotency_key == key))
                if not old or old.request_hash != digest:
                    raise HTTPException(409, "同じキーで異なる設定は登録できません")
                return old.id
    return job_id


def claim(db, lease_seconds=120):
    now, owner = utcnow(), str(uuid4())
    with db.session.begin() as s:
        # Re-execution is safe: caches are atomic and output is attempt-specific.
        s.execute(
            update(Job)
            .where(Job.status.in_(ACTIVE), Job.lease_until < now)
            .values(
                status="queued",
                lease_owner=None,
                lease_until=None,
                current_step="Worker停止を検出・再開待ち",
            )
        )
        query = (
            select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
        )
        if db.engine.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = s.scalar(query)
        if not job:
            return None
        changed = s.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == "queued")
            .values(
                status="downloading" if job.kind == "update" else "preprocessing",
                lease_owner=owner,
                lease_until=now + timedelta(seconds=lease_seconds),
                started_at=job.started_at or now,
                attempts=Job.attempts + 1,
                error_message=None,
                completed_at=None,
                progress_percent=0,
            )
        ).rowcount
        if not changed:
            return None
        return job.id, owner


class LeaseLost(RuntimeError):
    pass


def touch(db, job_id, owner, lease_seconds=120, **values):
    with db.session.begin() as s:
        values["lease_until"] = utcnow() + timedelta(seconds=lease_seconds)
        changed = s.execute(
            update(Job)
            .where(Job.id == job_id, Job.lease_owner == owner, Job.status.in_(ACTIVE))
            .values(**values)
        ).rowcount
        if not changed:
            raise LeaseLost("Job lease no longer belongs to this worker")


def job_dict(s, job):
    c = s.get(Config, job.id)
    return {
        "id": job.id,
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress_percent": job.progress_percent,
        "current_step": job.current_step,
        "processed_items": job.processed_items,
        "total_items": job.total_items,
        "created_at": job.created_at.isoformat() + "Z",
        "started_at": job.started_at.isoformat() + "Z" if job.started_at else None,
        "completed_at": job.completed_at.isoformat() + "Z"
        if job.completed_at
        else None,
        "error_message": job.error_message,
        "attempts": job.attempts,
        "summary": job.summary,
        "config": c.request,
        "artifacts": list(job.artifacts),
    }
