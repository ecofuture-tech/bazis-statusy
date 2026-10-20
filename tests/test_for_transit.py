# Copyright 2026 EcoFuture Technology Services LLC and contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
The meta `for_transit` of a list: the transits the user may make on each object of the page
(`allow_transits` of the item: the transit permissions by selector and status, from its
status), without the validators, in a number of queries that does not grow with the page.
"""

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit, TransitRelation
from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase
from bazis.contrib.users import get_user_model


User = get_user_model()

URL = '/api/v1/entity/parent_entity/'
#: the route set that declares the transit again with public=True
GUEST_URL = '/api/v1/entity/parent_entity_guest/'
NAME = to_attribute('name')

#: draft -> check (to_check), draft -> cancel (to_cancel), check -> active (to_active);
#: active and cancel are terminal
TRANSITS = [
    ('to_check', 'draft', 'check'),
    ('to_cancel', 'draft', 'cancel'),
    ('to_active', 'check', 'active'),
]

VIEW = 'entity.parent_entity.item.view.all.all'
ROLES = {
    # the author moves his drafts, anyone activates what is checked
    'editor': [
        VIEW,
        'entity.parent_entity.item.transit.author.draft.to_check',
        'entity.parent_entity.item.transit.author.draft.to_cancel',
        'entity.parent_entity.item.transit.all.check.to_active',
    ],
    # a transit permission of any status: still only from the status the transit starts at
    'checker': [VIEW, 'entity.parent_entity.item.transit.all.all.to_check'],
    'viewer': [VIEW],
}


@pytest.fixture
def workflow(db):
    cache.clear()
    StatusyContentType.objects.clear_cache()
    content_type = StatusyContentType.objects.get_for_model(ParentEntity)
    statuses = {
        it: Status.objects.get_or_create(id=it, defaults={NAME: it})[0]
        for it in ('draft', 'check', 'active', 'cancel')
    }
    for transit_id, src, dst in TRANSITS:
        Transit.objects.update_or_create(
            id=transit_id,
            defaults={
                NAME: transit_id,
                'model': content_type,
                'status_src': statuses[src],
                'status_dst': statuses[dst],
            },
        )

    users = {}
    for slug, permissions in ROLES.items():
        group = GroupPermission.objects.create(slug=slug, **{NAME: slug})
        for it in permissions:
            group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
        role = Role.objects.create(slug=slug, **{NAME: slug})
        role.groups_permission.add(group)
        users[slug] = User.objects.create_user(slug, email=f'{slug}@site.com', password='weak_1')
        users[slug].roles.add(role)
    yield statuses, users
    cache.clear()


def entity(name, status, author=None):
    return ParentEntity.objects.create(
        name=name, status=status, author=author, dt_approved=timezone.now()
    )


def for_transit(sample_app, user=None, url=URL, **params):
    response = get_api_client(sample_app, user.jwt_build() if user else None).get(
        url, params={'meta': 'for_transit', 'page[limit]': 100, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()['meta']['for_transit']


@pytest.mark.django_db(transaction=True)
def test_for_transit_by_selector_and_status(sample_app, workflow):
    statuses, users = workflow
    editor = users['editor']
    own_draft = entity('own draft', statuses['draft'], editor)
    other_draft = entity('other draft', statuses['draft'], users['viewer'])
    checked = entity('checked', statuses['check'], users['viewer'])
    entity('active', statuses['active'], editor)
    entity('cancelled', statuses['cancel'], editor)

    # the selector (author) and the status of the permissions, the transits of the status;
    # the ids sorted, the objects without one left out
    expected = {
        str(own_draft.pk): ['to_cancel', 'to_check'],
        str(checked.pk): ['to_active'],
    }
    assert for_transit(sample_app, editor) == expected

    # the transits of the item (state_actions: no transit here is the child of a
    # TransitRelation, which it would nest under its parent)
    for item in (own_draft, other_draft, checked):
        assert sorted(state_transits(sample_app, editor, item)) == expected.get(str(item.pk), [])

    # a transit permission of every status gives the transit only from its own status
    assert for_transit(sample_app, users['checker']) == {
        str(own_draft.pk): ['to_check'],
        str(other_draft.pk): ['to_check'],
    }

    # the meta follows the page and the filter of the list
    assert for_transit(sample_app, editor, filter='status=check') == {
        str(checked.pk): ['to_active']
    }
    assert for_transit(sample_app, editor, filter='status=active') == {}


@pytest.mark.django_db(transaction=True)
def test_for_transit_conditions_of_one_transit(sample_app, workflow):
    """
    Several permissions of the groups of a role give one transit under different conditions:
    the object gets it once if it matches any of them. A selector with the status `all`
    gives the transits of every status of the objects it selects.
    """
    statuses, users = workflow
    role = Role.objects.create(slug='overlap', **{NAME: 'overlap'})
    for slug, permissions in (
        (
            'overlap_author',
            [
                VIEW,
                'entity.parent_entity.item.transit.author.draft.to_check',
                'entity.parent_entity.item.transit.author.all.to_check',
                'entity.parent_entity.item.transit.author.all.to_active',
            ],
        ),
        ('overlap_all', ['entity.parent_entity.item.transit.all.draft.to_check']),
    ):
        group = GroupPermission.objects.create(slug=slug, **{NAME: slug})
        for it in permissions:
            group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
        role.groups_permission.add(group)
    user = User.objects.create_user('overlap', email='overlap@site.com', password='weak_1')
    user.roles.add(role)

    own_draft = entity('own draft', statuses['draft'], user)
    other_draft = entity('other draft', statuses['draft'], users['viewer'])
    own_checked = entity('own checked', statuses['check'], user)
    entity('other checked', statuses['check'], users['viewer'])
    entity('own active', statuses['active'], user)

    assert for_transit(sample_app, user) == {
        str(own_draft.pk): ['to_check'],
        str(other_draft.pk): ['to_check'],
        str(own_checked.pk): ['to_active'],
    }


@pytest.mark.django_db(transaction=True)
def test_for_transit_without_permission(sample_app, workflow):
    statuses, users = workflow
    entity('draft', statuses['draft'], users['viewer'])
    entity('checked', statuses['check'], users['viewer'])

    # no transit permission: nothing, though the user is the author and views the objects
    assert for_transit(sample_app, users['viewer']) == {}

    # after the transit the object is in a status without one of his transits
    editor = users['editor']
    item = entity('own draft', statuses['draft'], editor)
    assert for_transit(sample_app, editor)[str(item.pk)] == ['to_cancel', 'to_check']
    response = get_api_client(sample_app, editor.jwt_build()).post(
        f'{URL}{item.pk}/transit/', json_data={'transit': 'to_cancel'}
    )
    assert response.status_code == 200, response.text
    assert str(item.pk) not in for_transit(sample_app, editor)


def state_transits(sample_app, user, item, url=URL):
    """The transit ids of `state_actions` of the item, a nested list for a related set."""
    response = get_api_client(sample_app, user.jwt_build() if user else None).get(
        f'{url}{item.pk}/', params={'meta': 'state_actions'}
    )
    assert response.status_code == 200, response.text

    def transit_id(action):
        if isinstance(action, list):
            return [transit_id(it) for it in action]
        return action['endpoint']['body']['properties']['transit']['default']

    return [transit_id(it) for it in response.json()['meta']['state_actions']]


@pytest.mark.django_db(transaction=True)
def test_for_transit_leaves_out_the_child_of_a_transit_relation(sample_app, workflow):
    """
    `for_transit` lists the transits of the top level of `state_actions`: the child of a
    `TransitRelation` is left out, as `state_actions` shows it only under its parent.
    """
    statuses, users = workflow
    editor = users['editor']
    item = entity('own draft', statuses['draft'], editor)
    relation = TransitRelation.objects.create(
        transit_parent_id='to_check', transit_child_id='to_cancel', item_selector=''
    )

    assert for_transit(sample_app, editor) == {str(item.pk): ['to_check']}
    assert state_transits(sample_app, editor, item) == [['to_check', 'to_cancel']]

    # without the relation the child is a transit of the top level again
    relation.delete()
    assert for_transit(sample_app, editor) == {str(item.pk): ['to_cancel', 'to_check']}
    assert sorted(state_transits(sample_app, editor, item)) == ['to_cancel', 'to_check']


@pytest.mark.django_db(transaction=True)
def test_public_transit_does_not_widen_the_role(sample_app, workflow):
    """
    `public=True` opens the transit of the guest route set to anonymous users; an
    authenticated user there has the transits of his role, none without a transit permission.
    """
    statuses, users = workflow
    viewer, editor = users['viewer'], users['editor']
    other = entity('other draft', statuses['draft'], viewer)
    own = entity('own draft', statuses['draft'], editor)

    assert for_transit(sample_app, viewer, url=GUEST_URL) == {}
    assert state_transits(sample_app, viewer, other, url=GUEST_URL) == []
    response = get_api_client(sample_app, viewer.jwt_build()).post(
        f'{GUEST_URL}{other.pk}/transit/', json_data={'transit': 'to_check'}
    )
    assert response.status_code == 403

    # the transits of his role, as on the main route set
    assert for_transit(sample_app, editor, url=GUEST_URL) == {
        str(own.pk): ['to_cancel', 'to_check']
    }
    assert sorted(state_transits(sample_app, editor, own, url=GUEST_URL)) == [
        'to_cancel',
        'to_check',
    ]


@pytest.fixture
def guest(workflow):
    """A role for anonymous users with `to_check` from `draft`; a draft and a checked entity."""
    statuses, __ = workflow
    group = GroupPermission.objects.create(slug='guest', **{NAME: 'guest'})
    for it in (VIEW, 'entity.parent_entity.item.transit.all.draft.to_check'):
        group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
    role = Role.objects.create(slug='guest', for_anonymous=True, **{NAME: 'guest'})
    role.groups_permission.add(group)
    entity('checked', statuses['check'])
    return entity('draft', statuses['draft'])


@pytest.mark.django_db(transaction=True)
def test_for_transit_anonymous_main_route(sample_app, guest):
    """
    The transit of the main route set is not public: it refuses an anonymous user (403)
    whatever his role, so he gets no transit there.
    """
    assert for_transit(sample_app) == {}


@pytest.mark.django_db(transaction=True)
def test_for_transit_anonymous_guest_route(sample_app, guest):
    """
    A route set that declares the transit with `public=True` gives the anonymous user the
    transits of the roles for anonymous users, those its transit accepts.
    """
    assert for_transit(sample_app, url=GUEST_URL) == {str(guest.pk): ['to_check']}
    response = get_api_client(sample_app).post(
        f'{GUEST_URL}{guest.pk}/transit/', json_data={'transit': 'to_check'}
    )
    assert response.status_code == 200, response.text


@pytest.mark.django_db(transaction=True)
def test_for_transit_queries(sample_app, workflow, monkeypatch):
    """
    The queries of the meta do not grow with the page: the page, the transits of the model
    and one query per condition of the permissions that gives a transit from a status of the
    page. Not requested, it is not computed.
    """
    statuses, users = workflow
    editor = users['editor']
    counts = []
    original = StatusyRouteSetBase.for_transit

    def counted(self):
        with CaptureQueriesContext(connection) as queries:
            result = original(self)
        counts.append(len(queries))
        return result

    monkeypatch.setattr(StatusyRouteSetBase, 'for_transit', counted)

    response = get_api_client(sample_app, editor.jwt_build()).get(URL)
    assert response.status_code == 200
    assert 'for_transit' not in response.json().get('meta', {})
    assert counts == []

    for size in (3, 30):
        ParentEntity.objects.all().delete()
        for i in range(size):
            entity(f'draft {i}', statuses['draft'], editor if i % 2 else users['viewer'])
            entity(f'checked {i}', statuses['check'], editor)
            entity(f'active {i}', statuses['active'], editor)
        result = for_transit(sample_app, editor)
        assert len(result) == size + size // 2

    small, large = counts
    assert small == large
    # the page (its count and its objects), the transits of the model, the conditions
    # author & draft and check
    assert large <= 5
    # a page of one status (a column of a board): no query for the conditions of the others
    assert len(for_transit(sample_app, editor, filter='status=check')) == 30
    assert counts[-1] == large - 1

    # leaving out the children of a TransitRelation costs no query
    TransitRelation.objects.create(
        transit_parent_id='to_check', transit_child_id='to_cancel', item_selector=''
    )
    result = for_transit(sample_app, editor)
    assert len(result) == 45
    assert not any('to_cancel' in it for it in result.values())
    assert counts[-1] == large

    # a user without a transit permission: no query
    counts.clear()
    assert for_transit(sample_app, users['viewer']) == {}
    assert counts == [0]
