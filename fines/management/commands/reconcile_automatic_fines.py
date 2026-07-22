from django.core.management.base import BaseCommand

from fines.services import reconcile_automatic_fines


class Command(BaseCommand):
    help = 'Create pending automatic fine candidates for passed weekly deadlines.'

    def handle(self, *args, **options):
        created = reconcile_automatic_fines()
        self.stdout.write(self.style.SUCCESS(f'Created {created} automatic fine candidate(s).'))
