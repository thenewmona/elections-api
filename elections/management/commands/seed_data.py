from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.utils import IntegrityError

import pendulum

from elections import models


class Command(BaseCommand):
    help = "Generate data for local development and review"

    def handle(self, *_args, **_kwargs):
        self.get_or_create_superuser()
        self.add_known_data()

    def get_or_create_superuser(self, username="admin", password="password"):
        try:
            user = User.objects.create_superuser(
                username=username,
                email=f"{username}@{settings.BASE_DOMAIN}",
                password=password,
            )
            self.stdout.write(f"Created new superuser: {user}")
        except IntegrityError:
            user = User.objects.get(username=username)
            self.stdout.write(f"Found existing superuser: {user}")

        return user

    def add_known_data(self):
        election, _ = models.Election.objects.get_or_create(
            name="State Primary",
            date=pendulum.parse("2018-08-07", tz='America/Detroit'),
            defaults=dict(active=True, mi_sos_id=675),
        )
        self.stdout.write(f"Added election: {election}")

        election, _ = models.Election.objects.get_or_create(
            name="State General",
            date=pendulum.parse("2018-11-06", tz='America/Detroit'),
            defaults=dict(active=True, mi_sos_id=676),
        )
        self.stdout.write(f"Added election: {election}")

        county, _ = models.DistrictCategory.objects.get_or_create(
            name="County"
        )
        self.stdout.write(f"Added category: {county}")

        jurisdiction, _ = models.DistrictCategory.objects.get_or_create(
            name="Jurisdiction"
        )
        self.stdout.write(f"Added category: {jurisdiction}")

        kent, _ = models.District.objects.get_or_create(
            category=county, name="Kent"
        )
        self.stdout.write(f"Added district: {kent}")

        grand_rapids, _ = models.District.objects.get_or_create(
            category=jurisdiction, name="City of Grand Rapids"
        )
        self.stdout.write(f"Added district: {grand_rapids}")

        poll, _ = models.Poll.objects.get_or_create(
            county=kent,
            jurisdiction=grand_rapids,
            ward=1,
            precinct='9',
            mi_sos_id=1828,
        )
        self.stdout.write(f"Added poll: {poll}")
