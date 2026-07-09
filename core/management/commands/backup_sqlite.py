from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.sqlite_backups import create_sqlite_backup


class Command(BaseCommand):
    help = "Create a timestamped verified backup of the SQLite database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backup-dir",
            default=settings.SQLITE_BACKUP_DIR,
            help="Directory where backup files are written. Relative paths are based on BASE_DIR.",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=settings.SQLITE_BACKUP_KEEP,
            help="Number of newest backup files to keep. Use 0 to keep everything.",
        )

    def handle(self, *args, **options):
        try:
            result = create_sqlite_backup(backup_dir=options["backup_dir"], keep=options["keep"])
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup created: {result.path} ({result.member_count} members, {result.payment_count} payments)"
            )
        )
