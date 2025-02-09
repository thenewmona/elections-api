from typing import Optional

import bugsnag
import log
from bs4 import element

from elections import helpers
from elections.models import (
    Candidate,
    District,
    DistrictCategory,
    Election,
    Party,
    Position,
    Precinct,
    Proposal,
)


def handle_header(table: element.Tag, **_) -> bool:
    td = table.find('td', class_='primarySection')
    if td:
        header = td.text.strip()
        log.debug(f'Found header: {header!r}')
        if "partisan section" in header.lower():
            return True
    return False


def handle_party_section(table: element.Tag, **_) -> Optional[Party]:
    if table.get('class') != ['primaryTable']:
        return None

    td = table.find('td', class_='partyHeading')
    section = td.text.strip()
    log.debug(f'Found section: {section!r}')
    name = section.split(' ')[0].title()
    return Party.objects.get(name=name)


def handle_partisan_positions(
    table: element.Tag,
    *,
    election: Election,
    precinct: Precinct,
    party: Optional[Party],
    **_,
) -> Optional[Position]:
    assert party, 'Party must be parsed before positions'
    if party.name == "Nonpartisan":
        return None
    if table.get('class') != ['tblOffice']:
        return None

    # Parse category

    category = None
    td = table.find(class_='division')
    if td:
        category_name = helpers.titleize(td.text)
        if category_name not in {"Congressional", "Legislative", "Delegate"}:
            log.debug(f'Parsing category from division: {td.text!r}')
            category = DistrictCategory.objects.get(name=category_name)

    if not category:
        td = table.find(class_='office')
        if td:
            office = helpers.titleize(td.text)

            if office == "United States Senator":
                log.debug(f'Parsing category from office: {td.text!r}')
                category = DistrictCategory.objects.get(name="State")

            elif office == "Representative In Congress":
                log.debug(f'Parsing category from office: {td.text!r}')
                category = DistrictCategory.objects.get(name="US Congress")
            elif office == "State Senator":
                log.debug(f'Parsing category from office: {td.text!r}')
                category = DistrictCategory.objects.get(name="State Senate")
            elif office == "Representative In State Legislature":
                log.debug(f'Parsing category from office: {td.text!r}')
                category = DistrictCategory.objects.get(name="State House")

            elif office == "Delegate to County Convention":
                log.debug(f'Parsing category from office: {td.text!r}')
                category = DistrictCategory.objects.get(name="Precinct")

    if not category:
        class_ = 'mobileOnly'
        td = table.find(class_=class_)
        if td:
            category_name = helpers.titleize(td.text)
            log.debug(f'Parsing category from {class_!r}: {td.text!r}')
            category = DistrictCategory.objects.get(name=category_name)

    log.info(f'Parsed {category!r}')
    assert category

    # Parse district

    district = None
    td = table.find(class_='office')
    if td:
        office = helpers.titleize(td.text)

        if office == "Governor":
            log.debug(f'Parsing district from office: {td.text!r}')
            district = District.objects.get(category=category, name="Michigan")
        elif office == "United States Senator":
            log.debug(f'Parsing district from office: {td.text!r}')
            district = District.objects.get(category=category, name="Michigan")

        elif category.name == "Precinct":
            log.debug(f'Parsing district from office: {td.text!r}')
            district = precinct

        elif category.name == "County":
            log.debug(f'Parsing district from office: {td.text!r}')
            district = precinct.county

        else:
            td = table.find(class_='term')
            log.debug(f'Parsing district from term: {td.text!r}')
            district_name = helpers.titleize(td.text)
            district, created = District.objects.get_or_create(
                category=category, name=district_name
            )
            if created:
                log.warn(f'Added missing district: {district}')

    log.info(f'Parsed {district!r}')
    assert district

    # Parse position

    office = table.find(class_='office').text
    term = table.find_all(class_='term')[-1].text
    log.debug(f'Parsing position from: {office!r} when {term!r}')
    position_name = helpers.titleize(office)
    seats = int(term.strip().split()[-1])
    if isinstance(district, Precinct):
        position_name = f'{position_name} ({party} | {district})'
        district = None
    position, _ = Position.objects.get_or_create(
        election=election,
        district=district,
        name=position_name,
        defaults={'seats': seats},
    )
    log.info(f'Parsed {position!r}')
    if position.seats != seats:
        bugsnag.notify(
            f'Number of seats for {position} differs: ' f'{position.seats} vs. {seats}'
        )

    # Add precinct

    position.precincts.add(precinct)
    position.save()

    # Parse candidates

    for td in table.find_all(class_='candidate'):
        log.debug(f'Parsing candidate: {td.text!r}')
        candidate_name = td.text.strip()

        if candidate_name == "No candidates on ballot":
            log.warn(f'No {party} candidates for {position}')
            break

        candidate, _ = Candidate.objects.get_or_create(
            name=candidate_name, party=party, position=position
        )
        log.info(f'Parsed {candidate!r}')

    return position


def handle_general_header(table: element.Tag, **_) -> bool:
    if table.get('class') == ['mainTable']:
        td = table.find('td', class_='section')
        log.debug(f'Found header: {td.text!r}')
        if "nonpartisan section" in td.text.lower():
            return True
    return False


def handle_nonpartisan_section(table: element.Tag, **_) -> Optional[Party]:
    if table.get('class') != ['generalTable']:
        return None

    td = table.find(class_='section')
    log.debug(f'Parsing party from section: {td.text!r}')
    assert helpers.titleize(td.text) == "Nonpartisan Section"
    party = Party.objects.get(name="Nonpartisan")
    log.info(f'Parsed {party!r}')
    return party


def handle_nonpartisan_positions(
    table: element.Tag, *, election: Election, precinct: Precinct, party: Party, **_
) -> Optional[Proposal]:
    assert party, 'Party must be parsed before positions'
    if party.name != "Nonpartisan":
        return None
    if table.get('class') != ['tblOffice']:
        return None

    # Parse category

    category = None
    td = table.find(class_='office')
    if td:
        office = helpers.titleize(td.text)
        log.debug(f'Parsing category from office: {td.text!r}')
        category = DistrictCategory.objects.get(
            name=helpers.clean_district_category(office)
        )

    log.info(f'Parsed {category!r}')
    assert category

    # Parse district

    district = None
    td = table.find(class_='term')
    if td:
        log.debug(f'Parsing district from term: {td.text!r}')
        district, created = District.objects.get_or_create(
            category=category, name=helpers.titleize(td.text)
        )
        # We expect all districts to exist in the system through crawling,
        # but circuit court districts are only created when checking status
        if created:
            log.warn(f'Added missing district: {district}')

    log.info(f'Parsed {district!r}')
    assert district

    # Parse position

    office = table.find(class_='office').text
    seats = table.find_all(class_='term')[-1].text
    log.debug(f'Parsing position from: {office!r} when {seats!r}')
    position, _ = Position.objects.get_or_create(
        election=election,
        district=district,
        name=helpers.titleize(office),
        seats=int(seats.strip().split()[-1]),
    )
    log.info(f'Parsed {position!r}')
    assert position

    # Add precinct

    position.precincts.add(precinct)
    position.save()

    # Parse candidates

    for td in table.find_all(class_='candidate'):
        log.debug(f'Parsing candidate: {td.text!r}')
        candidate_name = td.text.strip()

        if candidate_name == "No candidates on ballot":
            log.warn(f'No {party} candidates for {position}')
            break

        candidate, _ = Candidate.objects.get_or_create(
            name=candidate_name, party=party, position=position
        )
        log.info(f'Parsed {candidate!r}')

    return position


def handle_proposals_header(table: element.Tag, **_) -> bool:
    if table.get('class') == None:
        td = table.find('td', class_='section')
        if td:
            header = td.text.strip()
            log.debug(f'Found header: {header!r}')
            return True
    return False


def handle_proposals(
    table: element.Tag,
    *,
    election: Election,
    precinct: Precinct,
    district: Optional[District],
    **_,
) -> Optional[Proposal]:
    if table.get('class') != ['proposal']:
        return None

    # Parse category

    category = None
    td = table.find(class_='division')
    if td:
        log.debug(f'Parsing category from division: {td.text!r}')
        category_name = helpers.clean_district_category(
            helpers.titleize(td.text.split("PROPOSALS")[0])
        )
        if category_name == "Authority":
            log.warn('Assuming category is county')
            category_name = "County"
        category = DistrictCategory.objects.get(name=category_name)
    else:
        log.debug(f'Reusing category from previous district: {district}')
        assert district
        category = district.category

    log.info(f'Parsed {category!r}')
    assert category

    # Parse district

    if category.name == "State":
        log.debug('Inferring district as state')
        district = District.objects.get(category=category, name="Michigan")
    elif category.name == "County":
        log.debug('Inferring district as county')
        district = precinct.county
    elif category.name in {"Jurisdiction", "City", "Township"}:
        log.debug('Inferring district as jurisdiction')
        district = precinct.jurisdiction
    else:
        proposal_title = table.find(class_='proposalTitle').text
        proposal_text = table.find(class_='proposalText').text
        log.debug(f'Parsing district from title: {proposal_title!r}')
        title = helpers.titleize(proposal_title)
        if category.name in title:
            district = District.objects.get(
                category=category, name=title.split(category.name)[0].strip()
            )
        elif precinct.jurisdiction.name in proposal_text:
            log.warn('Assuming district is jurisdiction from proposal')
            district = precinct.jurisdiction
        elif precinct.county.name in proposal_text:
            log.warn('Assuming district is county from proposal')
            district = precinct.county
        else:
            assert 0, f'Could not determine district: {table}'

    log.info(f'Parsed {district!r}')
    assert district

    # Parse proposal

    proposal_title = table.find(class_='proposalTitle').text
    proposal_text = table.find(class_='proposalText').text
    log.debug(f'Parsing proposal from text: {proposal_text!r}')
    proposal, _ = Proposal.objects.get_or_create(
        election=election,
        district=district,
        name=helpers.titleize(proposal_title),
        description=proposal_text.strip(),
    )
    log.info(f'Parsed {proposal!r}')

    # Add precinct

    proposal.precincts.add(precinct)
    proposal.save()

    return proposal
