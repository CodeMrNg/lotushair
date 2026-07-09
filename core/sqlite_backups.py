import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone


@dataclass
class SQLiteBackupResult:
    path: Path
    member_count: int
    payment_count: int


def get_backup_dir(backup_dir=None):
    resolved_backup_dir = Path(backup_dir or settings.SQLITE_BACKUP_DIR)
    if not resolved_backup_dir.is_absolute():
        resolved_backup_dir = Path(settings.BASE_DIR) / resolved_backup_dir
    return resolved_backup_dir


def create_sqlite_backup(backup_dir=None, keep=None):
    database = settings.DATABASES["default"]
    if database["ENGINE"] != "django.db.backends.sqlite3":
        raise RuntimeError("SQLite backup is only available for the sqlite3 database backend.")

    source_path = Path(database["NAME"])
    if not source_path.exists():
        raise RuntimeError(f"SQLite database not found: {source_path}")

    resolved_backup_dir = get_backup_dir(backup_dir)
    resolved_backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    backup_path = resolved_backup_dir / f"{source_path.stem}-{timestamp}{source_path.suffix}"

    try:
        with sqlite3.connect(source_path, timeout=settings.SQLITE_BACKUP_TIMEOUT_SECONDS) as source_connection:
            with sqlite3.connect(backup_path) as backup_connection:
                source_connection.backup(backup_connection)

        with sqlite3.connect(backup_path) as verification_connection:
            integrity = verification_connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                backup_path.unlink(missing_ok=True)
                raise RuntimeError(f"Backup integrity check failed: {integrity}")
            member_count = verification_connection.execute("SELECT COUNT(*) FROM core_member").fetchone()[0]
            payment_count = verification_connection.execute("SELECT COUNT(*) FROM core_payment").fetchone()[0]
    except sqlite3.Error as exc:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"Could not create SQLite backup: {exc}") from exc

    prune_backups(
        resolved_backup_dir,
        source_path.stem,
        source_path.suffix,
        settings.SQLITE_BACKUP_KEEP if keep is None else keep,
    )
    return SQLiteBackupResult(backup_path, member_count, payment_count)


def prune_backups(backup_dir, database_stem, database_suffix, keep):
    if keep <= 0:
        return

    backups = sorted(
        backup_dir.glob(f"{database_stem}-*{database_suffix}"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink(missing_ok=True)


def should_create_automatic_backup(backup_dir=None):
    if not settings.SQLITE_BACKUP_AUTO_ENABLED:
        return False

    interval_seconds = settings.SQLITE_BACKUP_INTERVAL_SECONDS
    if interval_seconds <= 0:
        return True

    marker_path = get_backup_dir(backup_dir) / ".last_backup"
    if not marker_path.exists():
        return True

    age_seconds = timezone.now().timestamp() - marker_path.stat().st_mtime
    return age_seconds >= interval_seconds


def mark_automatic_backup_created(backup_dir=None):
    marker_path = get_backup_dir(backup_dir) / ".last_backup"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(timezone.now().isoformat(), encoding="utf-8")


def acquire_backup_lock(backup_dir=None):
    lock_path = get_backup_dir(backup_dir) / ".backup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        stale_after = settings.SQLITE_BACKUP_LOCK_STALE_SECONDS
        age_seconds = timezone.now().timestamp() - lock_path.stat().st_mtime
        if age_seconds > stale_after:
            lock_path.unlink(missing_ok=True)

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None

    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        lock_file.write(str(os.getpid()))
    return lock_path


def release_backup_lock(lock_path):
    if lock_path:
        lock_path.unlink(missing_ok=True)
