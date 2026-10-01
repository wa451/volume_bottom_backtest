from datetime import datetime, timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url):
        sqlite = str(url).startswith("sqlite:")
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 30} if sqlite else {},
        )
        if sqlite:

            @event.listens_for(self.engine, "connect")
            def configure(conn, record):
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA journal_mode=WAL")

        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        from . import models  # noqa: F401 -- Register the version 1 schema.

        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                # API and Worker may boot concurrently on different machines.
                connection.execute(text("SELECT pg_advisory_xact_lock(613411321)"))
            elif self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            Base.metadata.create_all(connection)
