from pathlib import PurePosixPath
from uuid import uuid4
import os
import shutil
from filelock import FileLock
import httpx


class Storage:
    """Artifact keys are DB-owned; credentials never reach browser responses."""

    def __init__(self, settings):
        self.c = settings
        self.bucket = os.getenv("STORAGE_BUCKET", "backtests")
        if settings.storage_backend == "supabase":
            self.url = (
                os.environ["SUPABASE_URL"].rstrip("/")
                + "/storage/v1/object/"
                + self.bucket
            )
            self.headers = {
                "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"],
                "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            }
        elif settings.storage_backend == "s3":
            import boto3

            self.s3 = boto3.client(
                "s3",
                endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
                region_name=os.getenv("AWS_REGION", "ap-northeast-1"),
            )

    @staticmethod
    def valid_key(key):
        p = PurePosixPath(key)
        if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in key:
            raise ValueError("Invalid artifact key")
        return key

    def put(self, path, key):
        key = self.valid_key(key)
        if self.c.storage_backend == "local":
            dest = self.c.storage_dir / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + "." + uuid4().hex + ".tmp")
            shutil.copyfile(path, tmp)
            tmp.replace(dest)
        elif self.c.storage_backend == "supabase":
            with path.open("rb") as f, httpx.Client(timeout=300) as client:
                response = client.post(
                    self.url + "/" + key,
                    headers={
                        **self.headers,
                        "Content-Type": "application/octet-stream",
                        "x-upsert": "true",
                        "Content-Length": str(path.stat().st_size),
                    },
                    content=f,
                )
                response.raise_for_status()
        else:
            self.s3.upload_file(str(path), self.bucket, key)
        return key

    def get(self, key):
        key = self.valid_key(key)
        if self.c.storage_backend == "local":
            path = self.c.storage_dir / key
            if not path.is_file():
                raise FileNotFoundError("Artifact is unavailable")
            return path
        dest = self.c.cache_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(dest) + ".lock", timeout=300):
            if dest.exists():
                return dest
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            try:
                if self.c.storage_backend == "supabase":
                    with httpx.stream(
                        "GET", self.url + "/" + key, headers=self.headers, timeout=300
                    ) as response:
                        response.raise_for_status()
                        with tmp.open("wb") as f:
                            for chunk in response.iter_bytes():
                                f.write(chunk)
                else:
                    self.s3.download_file(self.bucket, key, str(tmp))
                tmp.replace(dest)
            finally:
                tmp.unlink(missing_ok=True)
        return dest
