from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class S3LogArchiver:
    def __init__(
        self,
        *,
        enabled: bool,
        bucket: str,
        prefix: str,
        region: str | None,
        delete_local_after_upload: bool,
        upload_retries: int,
    ) -> None:
        self.enabled = enabled
        self.bucket = bucket.strip()
        self.prefix = prefix.strip().strip("/")
        self.region = region.strip() if region else None
        self.delete_local_after_upload = delete_local_after_upload
        self.upload_retries = max(1, upload_retries)
        self._client = None
        self._uploaded_folders: set[str] = set()
        self._lock = threading.Lock()
        self._repo_root = Path(__file__).resolve().parents[2]
        self._troubleshooting_dir = self._repo_root / "aws-troubleshooting"
        self._troubleshooting_file = self._troubleshooting_dir / "s3_upload_errors.txt"

    @classmethod
    def from_env(cls) -> "S3LogArchiver":
        enabled = _env_bool("LOG_ARCHIVE_S3_ENABLED", False)
        bucket = os.getenv("LOG_ARCHIVE_S3_BUCKET", "").strip()
        prefix = os.getenv("LOG_ARCHIVE_S3_PREFIX", "polymarket-logs")
        region = os.getenv("LOG_ARCHIVE_AWS_REGION")
        delete_local = _env_bool("LOG_ARCHIVE_DELETE_LOCAL_AFTER_UPLOAD", False)
        retries_raw = os.getenv("LOG_ARCHIVE_UPLOAD_RETRIES", "3").strip()
        try:
            retries = int(retries_raw)
        except ValueError:
            retries = 3
        return cls(
            enabled=enabled,
            bucket=bucket,
            prefix=prefix,
            region=region,
            delete_local_after_upload=delete_local,
            upload_retries=retries,
        )

    def archive_folder(self, folder: Path) -> bool:
        if not self.enabled:
            return False
        if not self.bucket:
            print("S3 archiver skipped: LOG_ARCHIVE_S3_BUCKET is empty.")
            return False
        if not folder.exists() or not folder.is_dir():
            return False
        csv_files = sorted(p for p in folder.glob("*.csv") if p.is_file())
        if not csv_files:
            return False

        folder_key = str(folder.resolve())
        with self._lock:
            if folder_key in self._uploaded_folders:
                return True

        client = self._get_client()
        if client is None:
            return False

        prefix = f"{self.prefix}/" if self.prefix else ""
        base_key = f"{prefix}{folder.name}"
        try:
            for csv_path in csv_files:
                object_key = f"{base_key}/{csv_path.name}"
                self._upload_with_retries(client, csv_path, object_key)
            marker_key = f"{base_key}/_UPLOAD_COMPLETE.txt"
            marker_body = f"uploaded_at_epoch={int(time.time())}\nfiles={len(csv_files)}\n"
            client.put_object(Bucket=self.bucket, Key=marker_key, Body=marker_body.encode("utf-8"))
            with self._lock:
                self._uploaded_folders.add(folder_key)
            print(f"S3 archive complete (bucket={self.bucket}, prefix={base_key}, files={len(csv_files)})")
            if self.delete_local_after_upload:
                self._delete_local_folder(folder, csv_files)
            return True
        except Exception as exc:
            print(f"S3 archive failed (folder={folder}): {exc}")
            self._log_troubleshooting_error(folder=folder, exc=exc, phase="archive_folder")
            return False

    def startup_preflight(self) -> None:
        if not self.enabled:
            return
        if not self.bucket:
            exc = RuntimeError("LOG_ARCHIVE_S3_BUCKET is empty while LOG_ARCHIVE_S3_ENABLED=true.")
            self._log_troubleshooting_error(folder=Path("logs"), exc=exc, phase="startup_preflight")
            raise exc
        client = self._get_client()
        if client is None:
            exc = RuntimeError("boto3 is not installed or S3 client initialization failed.")
            self._log_troubleshooting_error(folder=Path("logs"), exc=exc, phase="startup_preflight")
            raise exc
        try:
            client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            self._log_troubleshooting_error(folder=Path("logs"), exc=exc, phase="startup_preflight")
            raise

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
        except Exception:
            print("S3 archiver disabled: boto3 is not installed.")
            return None
        access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
        session_token = os.getenv("AWS_SESSION_TOKEN", "").strip()
        region_name = self.region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")

        session_kwargs: dict[str, str] = {}
        if region_name:
            session_kwargs["region_name"] = region_name
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                session_kwargs["aws_session_token"] = session_token

        session = boto3.session.Session(**session_kwargs) if session_kwargs else boto3.session.Session()
        self._client = session.client("s3")
        return self._client

    def _upload_with_retries(self, client, src: Path, key: str) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, self.upload_retries + 1):
            try:
                client.upload_file(str(src), self.bucket, key)
                return
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                if attempt < self.upload_retries:
                    time.sleep(1.0 * attempt)
        if last_exc is not None:
            raise last_exc

    def _delete_local_folder(self, folder: Path, csv_files: list[Path]) -> None:
        try:
            for path in csv_files:
                path.unlink(missing_ok=True)
            # Remove the directory only if no other files remain.
            next(folder.iterdir())
        except StopIteration:
            try:
                folder.rmdir()
            except Exception:
                pass
        except Exception as exc:
            print(f"S3 archive local cleanup failed (folder={folder}): {exc}")

    def _is_s3_troubleshooting_error(self, exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            error = response.get("Error")
            if isinstance(error, dict):
                code = str(error.get("Code", "")).strip()
                if code in {
                    "NoSuchBucket",
                    "AccessDenied",
                    "AllAccessDisabled",
                    "InvalidAccessKeyId",
                    "SignatureDoesNotMatch",
                    "ExpiredToken",
                }:
                    return True
        text = str(exc)
        lowered = text.lower()
        return (
            "nosuchbucket" in lowered
            or "accessdenied" in lowered
            or "forbidden" in lowered
            or "status code: 403" in lowered
        )

    def _log_troubleshooting_error(self, folder: Path, exc: Exception, phase: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        message = (
            f"[{ts}] phase={phase} bucket={self.bucket} prefix={self.prefix} "
            f"folder={folder} error={exc}\n"
        )
        try:
            with self._lock:
                self._troubleshooting_dir.mkdir(parents=True, exist_ok=True)
                with self._troubleshooting_file.open("a", encoding="utf-8") as fh:
                    fh.write(message)
        except Exception as log_exc:
            print(f"S3 troubleshooting log write failed: {log_exc}")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
