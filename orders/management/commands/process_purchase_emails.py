from datetime import timedelta
from time import sleep

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections
from django.db.models import Count, Q
from django.utils import timezone

from orders.models import PurchaseEmailJob
from orders.purchase_notifications import deliver_due_purchase_emails


class Command(BaseCommand):
    help = 'Send due purchase emails. Use --watch to keep processing the queue.'

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument('--watch', action='store_true')
        modes.add_argument('--status', action='store_true')
        modes.add_argument('--retry-job', type=int, metavar='ID')

    def handle(self, *args, **options):
        State = PurchaseEmailJob.State
        jobs = PurchaseEmailJob.objects.all()
        if options['status']:
            counts = dict(jobs.values_list('state').annotate(total=Count('pk')))
            for state in State:
                self.stdout.write(f'{state.value}: {counts.get(state.value, 0)}')
            flagged = jobs.filter(state__in=[State.FAILED, State.SENDING]).order_by('pk')
            for pk, state in flagged.values_list('pk', 'state')[:20]:
                self.stdout.write(f'Job {pk}: {state}')
            return

        if options['retry_job'] is not None:
            now = timezone.now()
            changed = jobs.filter(pk=options['retry_job']).filter(
                Q(state=State.FAILED)
                | Q(state=State.SENDING, claimed_at__lt=now - timedelta(minutes=15)),
            ).update(state=State.PENDING, claimed_at=None, available_at=now, attempts=0)
            if not changed:
                raise CommandError('Job is not failed or has been claimed for less than 15 minutes.')
            self.stdout.write(f'Job {options["retry_job"]} queued for retry.')
            return

        if not options['watch']:
            self.report(deliver_due_purchase_emails())
            return

        self.stdout.write('Purchase email worker running. Press Ctrl+C to stop.')
        try:
            while True:
                close_old_connections()
                try:
                    results = deliver_due_purchase_emails()
                except OperationalError:
                    self.stderr.write("Database unavailable; retrying queue access in 3 seconds.")
                    sleep(3)
                    continue
                if results:
                    self.report(results)
                else:
                    sleep(3)
        except KeyboardInterrupt:
            self.stdout.write('Purchase email worker stopped.')

    def report(self, results):
        self.stdout.write(
            f'Sent: {results["sent"]}; retry scheduled: {results["pending"]}; '
            f'failed: {results["failed"]}; skipped: {results["skipped"]}.'
        )
