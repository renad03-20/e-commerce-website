"""Move existing commission uploads out of public MEDIA_ROOT, preserving names."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from django.core.management.base import BaseCommand, CommandError
from artwork.models import CustomRequest, CommissionMessage, CommissionDelivery
from artwork.private_storage import PRIVATE_PREFIXES, private_root, public_root, private_name


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.digest()


def copy_verified(source, destination, expected):
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.protect-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with source.open('rb') as original:
                shutil.copyfileobj(original, stream, length=1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
            if digest(temporary) != expected:
                raise CommandError(f'File changed during copy; original retained: {source.name}')
            # Publish without replacing another file, even if interrupted/retried.
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.is_symlink() or digest(destination) != expected:
                    raise CommandError(f'Private destination differs; original retained: {source.name}')
        finally:
            temporary.unlink(missing_ok=True)
    if digest(destination) != expected or digest(source) != expected:
        raise CommandError(f'Verification failed; original retained: {source.name}')


class Command(BaseCommand):
    help = 'Move commission reference images, message attachments and deliveries into private storage after verifying their contents.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Validate and report without moving files.')

    def handle(self, *args, **options):
        public, private = public_root(), private_root()
        plan = []
        for prefix in sorted(PRIVATE_PREFIXES):
            folder = public / prefix
            if folder.is_symlink():
                raise CommandError(f'Refusing a symbolic-link upload directory: {prefix}')
            if not folder.exists():
                continue
            for source in sorted(folder.rglob('*')):
                if source.is_symlink():
                    raise CommandError(f'Refusing a symbolic-link upload: {source.name}')
                if source.is_dir():
                    continue
                if not source.is_file():
                    raise CommandError(f'Refusing a non-file upload: {source.name}')
                name = private_name(source.relative_to(public).as_posix())
                destination = private / name
                if not destination.resolve().is_relative_to(private) or destination.is_symlink():
                    raise CommandError(f'Unsafe private destination: {name}')
                expected = digest(source)
                if destination.exists() and (not destination.is_file() or digest(destination) != expected):
                    raise CommandError(f'Private destination already contains different bytes: {name}. No files were moved.')
                plan.append((source, destination, expected))
        if options['dry_run']:
            self.stdout.write(f'Would protect {len(plan)} existing file(s). No files moved.')
            return
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        for source, destination, expected in plan:
            if not destination.exists():
                copy_verified(source, destination, expected)
            if destination.is_symlink() or digest(destination) != expected or digest(source) != expected:
                raise CommandError(f'Verification failed; public original retained: {source.name}')
            source.unlink()
        # Also removes now-empty directories; no recursive deletion of files.
        for prefix in PRIVATE_PREFIXES:
            folder = public / prefix
            if folder.exists():
                for directory in sorted((p for p in folder.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                    try: directory.rmdir()
                    except OSError: pass
                try: folder.rmdir()
                except OSError: pass
        self.stdout.write(self.style.SUCCESS(f'Protected {len(plan)} existing file(s). Public copies removed after verification.'))
        missing = 0
        for model, field in ((CustomRequest, 'reference_image'), (CommissionMessage, 'attachment'), (CommissionDelivery, 'delivery_file')):
            for name in model.objects.exclude(**{field: ''}).exclude(**{field+'__isnull': True}).values_list(field, flat=True):
                try:
                    name = private_name(name)
                except Exception:
                    missing += 1
                    continue
                if not (private / name).is_file():
                    missing += 1
        if missing:
            self.stderr.write(self.style.WARNING(f'{missing} referenced file(s) are already missing or invalid. Database references were left unchanged; restore those files from your backup.'))
