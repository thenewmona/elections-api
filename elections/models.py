from __future__ import annotations

import random
from typing import List, Optional, Union

from django.db import models
from django.utils import timezone

import bugsnag
import log
import pendulum
import requests
from bs4 import BeautifulSoup, element
from model_utils.models import TimeStampedModel

from . import helpers


class DistrictCategory(TimeStampedModel):
    """Types of regions bound to ballot items."""

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name_plural = "District Categories"
        ordering = ['name']

    def __str__(self) -> str:
        if self.name in {"County", "Jurisdiction", "City", "Township"}:
            return self.name
        return f'{self.name} District'


class District(TimeStampedModel):
    """Districts bound to ballot items."""

    category = models.ForeignKey(DistrictCategory, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    population = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = ['category', 'name']
        ordering = ['-population']

    def __repr__(self) -> str:
        return f'<District: {self.name} ({self.category})>'

    def __str__(self) -> str:
        return self.name


class Election(TimeStampedModel):
    """Point in time where voters can cast opinions on ballot items."""

    name = models.CharField(max_length=100)
    date = models.DateField()

    active = models.BooleanField(default=False)
    reference_url = models.URLField(blank=True, null=True)

    mi_sos_id = models.PositiveIntegerField()

    class Meta:
        unique_together = ['date', 'name']
        ordering = ['date']

    def __str__(self) -> str:
        return ' | '.join(self.mi_sos_name)

    @property
    def mi_sos_name(self) -> List[str]:
        return [
            self.name,
            pendulum.parse(self.date.isoformat()).format("dddd, MMMM D, YYYY"),
        ]


# https://vip-specification.readthedocs.io/en/vip52/built_rst/xml/elements/polling_location.html
# TODO: PollingLocation(TimestampedModel): ...


class Precinct(TimeStampedModel):
    """Specific region where all voters share a ballot."""

    county = models.ForeignKey(
        District, related_name='counties', on_delete=models.CASCADE
    )
    jurisdiction = models.ForeignKey(
        District, related_name='jurisdictions', on_delete=models.CASCADE
    )
    ward = models.CharField(max_length=2, blank=True)
    number = models.CharField(max_length=3, blank=True)

    mi_sos_id = models.PositiveIntegerField()

    class Meta:
        unique_together = ['county', 'jurisdiction', 'ward', 'number']
        ordering = ['mi_sos_id']

    def __str__(self) -> str:
        return ' | '.join(self.mi_sos_name)

    @property
    def mi_sos_name(self) -> List[str]:
        if self.ward and self.number:
            ward_precinct = f"Ward {self.ward} Precinct {self.number}"
        elif self.ward:
            # Extra space is intentional to match the MI SOS website format
            ward_precinct = f"Ward {self.ward} "
        else:
            assert (
                self.number
            ), f"Ward and precinct are missing: id={self.id} mi_sos_id={self.mi_sos_id}"  # pylint: disable=no-member
            # Extra space is intentional to match the MI SOS website format
            ward_precinct = f" Precinct {self.number}"
        return [
            f"{self.county} County, Michigan",
            f"{self.jurisdiction}, {ward_precinct}",
        ]

    def save(self, *args, **kwargs):
        self.ward = self.ward if self.ward.strip('0') else ''
        self.number = self.number if self.number.strip('0') else ''
        assert self.mi_sos_name
        super().save(*args, **kwargs)


class RegistrationStatus(models.Model):
    """Status of a particular voter's registration."""

    registered = models.BooleanField()
    precinct = models.ForeignKey(Precinct, null=True, on_delete=models.SET_NULL)
    # We can't use 'ManytoManyField' because this model is never saved
    districts: List[District] = []

    def save(self, *args, **kwargs):
        raise NotImplementedError


class Voter(models.Model):
    """Data needed to look up Michigan voter registration status."""

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    birth_date = models.DateField()
    zip_code = models.CharField(max_length=10)

    def __repr__(self) -> str:
        birth = pendulum.parse(str(self.birth_date)).format("YYYY-MM-DD")
        return f"<voter: {self}, birth={birth}, zip={self.zip_code}>"

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def birth_month(self) -> int:
        return self.birth_date.month

    @property
    def birth_year(self) -> int:
        return self.birth_date.year

    def fetch_registration_status(self) -> RegistrationStatus:
        data = helpers.fetch_registration_status_data(self)

        if not data['registered']:
            return RegistrationStatus(registered=False)

        districts: List[District] = []
        county = jurisdiction = None

        for category_name, district_name in sorted(data['districts'].items()):
            if not (category_name and district_name):
                log.warn("Skipped blank MI SOS district")
                continue

            if category_name in ["Ward", "Precinct"]:
                log.debug(f"Skipped category: {category_name}")
                continue

            category, created = DistrictCategory.objects.get_or_create(
                name=category_name
            )
            if created:
                log.info(f"New category: {category}")

            if category.name == "County":
                district_name = district_name.replace(" County", "")
            district, created = District.objects.get_or_create(
                category=category, name=district_name
            )
            if created:
                log.info(f"New district: {district}")

            districts.append(district)

            if district.category.name == "County":
                county = district
            if district.category.name == "Jurisdiction":
                jurisdiction = district

        precinct, created = Precinct.objects.get_or_create(
            county=county,
            jurisdiction=jurisdiction,
            ward=data['districts']['Ward'],
            number=data['districts']['Precinct'],
            defaults=dict(mi_sos_id=0),
        )
        if created:
            log.info(f"New precinct: {precinct}")
        if not precinct.mi_sos_id:
            bugsnag.notify(f'Precinct missing MI SOS ID: {precinct}')

        status = RegistrationStatus(registered=data['registered'], precinct=precinct)
        status.districts = districts

        return status

    def save(self, *args, **kwargs):
        raise NotImplementedError


# https://vip-specification.readthedocs.io/en/vip52/built_rst/xml/elements/party.html
class Party(TimeStampedModel):
    """Affiliation for a particular candidate."""

    name = models.CharField(max_length=50, unique=True, editable=False)
    color = models.CharField(max_length=7, blank=True, editable=False)

    class Meta:
        verbose_name_plural = "Parties"
        ordering = ['name']

    def __str__(self):
        return self.name


class Ballot(TimeStampedModel):
    """Full ballot bound to a particular polling location."""

    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    precinct = models.ForeignKey(Precinct, on_delete=models.CASCADE)

    class Meta:
        unique_together = ['election', 'precinct']
        ordering = ['election__date']

    def __str__(self) -> str:
        return ' | '.join(self.mi_sos_name)

    @property
    def mi_sos_name(self) -> List[str]:
        return self.election.mi_sos_name + self.precinct.mi_sos_name

    @property
    def mi_sos_url(self) -> str:
        return helpers.build_mi_sos_url(
            election_id=self.election.mi_sos_id, precinct_id=self.precinct.mi_sos_id
        )


class BallotWebsite(models.Model):
    """Raw HTML of potential ballot from the MI SOS website."""

    mi_sos_election_id = models.PositiveIntegerField()
    mi_sos_precinct_id = models.PositiveIntegerField()
    ballot = models.ForeignKey(
        Ballot, null=True, on_delete=models.SET_NULL, related_name='websites'
    )

    mi_sos_html = models.TextField(blank=True)

    source = models.NullBooleanField()
    fetched = models.BooleanField(default=False)
    valid = models.NullBooleanField()
    parsed = models.BooleanField(default=False)

    table_count = models.IntegerField(default=-1)
    refetch_weight = models.FloatField(default=1.0)

    last_fetch = models.DateTimeField(null=True, editable=False)
    last_fetch_with_precinct = models.DateTimeField(null=True, editable=False)
    last_fetch_with_ballot = models.DateTimeField(null=True, editable=False)
    last_parse = models.DateTimeField(null=True, editable=False)

    class Meta:
        unique_together = ['mi_sos_election_id', 'mi_sos_precinct_id']

    def __str__(self) -> str:
        return self.mi_sos_url

    @property
    def mi_sos_url(self) -> str:
        return helpers.build_mi_sos_url(
            election_id=self.mi_sos_election_id, precinct_id=self.mi_sos_precinct_id
        )

    @property
    def stale(self) -> bool:
        return self.refetch_weight > random.random()

    def fetch(self):
        url = self.mi_sos_url

        log.info(f'Fetching {url}')
        response = requests.get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Geck o/20100101 Firefox/40.1'
            },
            verify=False,
        )
        response.raise_for_status()
        self.fetched = True
        self.last_fetch = timezone.now()

        self.mi_sos_html = response.text.strip()
        if (
            "not available at this time" in self.mi_sos_html
            or " County" not in self.mi_sos_html
        ):
            log.warn('Ballot URL does contain precinct information')
            self.valid = False
            table_count = -1
        else:
            assert "Sample Ballot" in self.mi_sos_html
            log.info('Ballot URL contains precinct information')
            self.valid = True
            self.last_fetch_with_precinct = timezone.now()
            soup = BeautifulSoup(self.mi_sos_html, 'html.parser')
            table_count = len(soup.find_all('table'))
            if table_count:
                self.last_fetch_with_ballot = timezone.now()

        if table_count == self.table_count:
            min_weight = 1 / 14 if self.valid else 1 / 28
            self.refetch_weight = max(min_weight, self.refetch_weight / 2)
        elif self.table_count == -1:
            self.refetch_weight = 0.5
        else:
            if self.parsed and table_count:
                self.parsed = False
            self.refetch_weight = (self.refetch_weight + 1.0) / 2

        self.table_count = table_count
        self.refetch_weight = round(self.refetch_weight, 3)
        self.save()

    def parse(self):
        log.info(f'Parsing HTML for ballot: {self}')
        soup = BeautifulSoup(self.mi_sos_html, 'html.parser')

        log.debug(f'Getting precinct by ID: {self.mi_sos_precinct_id}')
        precinct = Precinct.objects.get(mi_sos_id=self.mi_sos_precinct_id)

        log.debug(f'Getting election by ID: {self.mi_sos_election_id}')
        election = Election.objects.get(mi_sos_id=self.mi_sos_election_id)

        party = district = None
        results = []
        for index, table in enumerate(soup.find_all('table')):
            result = self._handle_html_element(
                table,
                election=election,
                precinct=precinct,
                party=party,
                district=district,
            )

            if isinstance(result, (Party, Position, Proposal)):
                results.append(result)
            if isinstance(result, Position):
                candidates = result.candidates
                if (
                    candidates
                    and candidates.first()
                    and candidates.first().party.name == "Nonpartisan"
                ):
                    log.info('Start nonpartisan section')
                    party = candidates.first().party
            if isinstance(result, Party):
                party = result
            if isinstance(result, (Position, Proposal)):
                district = result.district

            if result:
                continue

            html = table.prettify()
            msg = f'Unexpected table ({index}) on {self.mi_sos_url}:\n\n{html}'
            raise ValueError(msg)

        self.parsed = True
        self.last_parse = timezone.now()
        self.save()

        return results

    @staticmethod
    def _handle_html_element(
        table: element.Tag,
        *,
        election: Election,
        precinct: Precinct,
        district: Optional[District],
        party: Optional[Party],
    ) -> Union[None, Party, Position, Proposal]:
        from . import legacy_parsers

        for handler in [
            # legacy_parsers.handle_primary_header,
            # legacy_parsers.handle_party_section,
            # legacy_parsers.handle_partisan_section,
            legacy_parsers.general.handle_main_wrapper,
            legacy_parsers.general.handle_general_wrapper,
            legacy_parsers.general.handle_partisan_section,
            # legacy_parsers.handle_general_header,
            legacy_parsers.general.handle_nonpartisan_section,
            # legacy_parsers.handle_nonpartisan_positions,
            legacy_parsers.general.handle_proposals_header,
            legacy_parsers.general.handle_proposals,
        ]:
            try:
                result = handler(  # type: ignore
                    table,
                    election=election,
                    precinct=precinct,
                    party=party,
                    district=district,
                )
            except Exception as e:
                print(table.prettify())
                raise e from None

            if result:
                return result

        return None


class BallotItem(TimeStampedModel):

    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    district = models.ForeignKey(District, on_delete=models.CASCADE, null=True)
    precincts = models.ManyToManyField(Precinct)

    name = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    reference_url = models.URLField(blank=True, null=True)

    class Meta:
        abstract = True


class Proposal(BallotItem):
    """Ballot item with a boolean outcome."""

    class Meta:
        unique_together = ['election', 'district', 'name']
        ordering = ['name']

    def __str__(self):
        return self.name


class Position(BallotItem):
    """Ballot item selecting one ore more candidates."""

    term = models.CharField(max_length=200)
    seats = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ['election', 'district', 'name', 'term', 'seats']
        ordering = ['name', 'seats']

    def __str__(self):
        if self.term:
            return f'{self.name} ({self.term})'
        return self.name


# https://vip-specification.readthedocs.io/en/vip52/built_rst/xml/elements/candidate.html
class Candidate(TimeStampedModel):
    """Individual running for a particular position."""

    position = models.ForeignKey(
        Position, null=True, on_delete=models.CASCADE, related_name='candidates'
    )

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    reference_url = models.URLField(blank=True, null=True)
    party = models.ForeignKey(Party, blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = ['position', 'name']
        ordering = ['name']

    def __str__(self) -> str:
        return f'{self.name} for {self.position}'
