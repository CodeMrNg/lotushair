import logging

from core.sqlite_backups import (
    acquire_backup_lock,
    create_sqlite_backup,
    mark_automatic_backup_created,
    release_backup_lock,
    should_create_automatic_backup,
)


logger = logging.getLogger(__name__)


class AutomaticSQLiteBackupMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self.create_backup_if_due()
        return response

    def create_backup_if_due(self):
        try:
            if not should_create_automatic_backup():
                return

            lock_path = acquire_backup_lock()
            if not lock_path:
                return

            try:
                if not should_create_automatic_backup():
                    return
                result = create_sqlite_backup()
                mark_automatic_backup_created()
                logger.info("Automatic SQLite backup created: %s", result.path)
            finally:
                release_backup_lock(lock_path)
        except Exception:
            logger.exception("Automatic SQLite backup failed")
