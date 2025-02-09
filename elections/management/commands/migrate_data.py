from django.core.management.base import BaseCommand

import log

from elections.models import District, DistrictCategory, Party


class Command(BaseCommand):
    help = "Migrate data between existing models and initialize constants"

    def handle(self, verbosity: int, **_kwargs):
        log.init(reset=True, verbosity=verbosity)

        self.initialize_parties()
        self.initialize_districts()

    def initialize_parties(self):
        for name, color in [
            # Placeholders
            ("Nonpartisan", '#999'),
            ("No Party Affiliation", '#999'),
            # Parties
            ("Democratic", '#3333FF'),
            ("Green", '#00A95C'),
            ("Libertarian", '#ECC850'),
            ("Natural Law", '#FFF7D6'),
            ("Republican", '#E81B23'),
            ("U.S. Taxpayers", '#A356DE'),
            ("Working Class", '#A30000'),
        ]:
            party, created = Party.objects.update_or_create(
                name=name, defaults=dict(color=color)
            )
            if created:
                self.stdout.write(f'Added party: {party}')

    def initialize_districts(self):
        state, created = DistrictCategory.objects.get_or_create(name="State")
        if created:
            self.stdout.write(f'Added district category: {state}')

        for name in [
            # State
            "County",
            "Jurisdiction",
            "Precinct",
            # Local
            "City",
            "District Library",
            "Local School",
            "Intermediate School",
            "Township",
            "Metropolitan",
            "Village",
            "Authority",
            "Library",
        ]:
            category, created = DistrictCategory.objects.get_or_create(name=name)
            if created:
                self.stdout.write(f'Added district category: {category}')

        michigan, created = District.objects.get_or_create(
            category=state, name="Michigan"
        )
        if created:
            self.stdout.write(f'Added district: {michigan}')
