import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Apply SQLite pragmas used by the web app and checkpoint the WAL file."

    def handle(self, *args, **options):
        database_name = settings.DATABASES["default"]["NAME"]
        try:
            connection = sqlite3.connect(database_name, timeout=5)
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
            journal_mode = cursor.fetchone()[0]
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA temp_store = MEMORY")
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            checkpoint = cursor.fetchone()
            cursor.execute("PRAGMA optimize")
            connection.close()
        except sqlite3.OperationalError as exc:
            raise CommandError(f"SQLite is still locked: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"SQLite journal_mode={journal_mode}, checkpoint={checkpoint}"))
