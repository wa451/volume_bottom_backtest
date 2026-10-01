from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv
from src.utils import ROOT

load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    data_root: Path = field(
        default_factory=lambda: Path(os.getenv("WEB_DATA_ROOT", str(ROOT))).resolve()
    )
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", f"sqlite:///{ROOT}/data/web.sqlite3"
        )
    )
    storage_backend: str = field(
        default_factory=lambda: os.getenv("STORAGE_BACKEND", "local")
    )
    storage_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("STORAGE_DIR", str(ROOT / "data/web/storage"))
        ).resolve()
    )
    cache_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("ARTIFACT_CACHE_DIR", str(ROOT / "data/web/artifact-cache"))
        ).resolve()
    )
    api_token: str = field(default_factory=lambda: os.getenv("API_TOKEN", ""))
    environment: str = field(
        default_factory=lambda: os.getenv("WEB_ENV", "development")
    )
    config_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("BACKTEST_CONFIG", str(ROOT / "config.yaml"))
        )
    )
    lease_seconds: int = 120

    def validate(self):
        if self.environment == "production":
            if not self.api_token or not self.database_url.startswith(
                ("postgres", "postgresql")
            ):
                raise ValueError(
                    "Production requires API_TOKEN and PostgreSQL DATABASE_URL"
                )
            if self.storage_backend == "local":
                raise ValueError(
                    "Production requires shared Supabase/S3 artifact storage"
                )
        if self.storage_backend not in ("local", "supabase", "s3"):
            raise ValueError("Unknown STORAGE_BACKEND")
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql+psycopg://", 1
            )
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        for p in (self.data_root / "data", self.storage_dir, self.cache_dir):
            p.mkdir(parents=True, exist_ok=True)
