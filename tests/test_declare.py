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
The statuses and transits declared in the code (`workflow.py`, bazis.contrib.statusy.declare)
and their application to the database after `migrate`.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.translation import gettext_lazy as _

import pytest
from entity.models import ChildEntity, ParentEntity

from bazis.contrib.permit.declare import Group
from bazis.contrib.statusy import declare
from bazis.contrib.statusy.checks import check_declarations, check_declarations_applied
from bazis.contrib.statusy.declare import (
    Status,
    Transit,
    Workflow,
    apply_declarations,
    declaration_messages,
    orphans,
)
from bazis.contrib.statusy.models import Status as StatusModel
from bazis.contrib.statusy.models import StatusyContentType
from bazis.contrib.statusy.models import Transit as TransitModel


DRAFT = Status('decl_draft', _('Draft'))
REVIEW = Status('decl_review', 'Review')
DONE = Status('decl_done', 'Done')


def workflow(*transits: Transit, statuses=(DRAFT, REVIEW, DONE)) -> Workflow:
    return Workflow('entity.ParentEntity', statuses, transits)


SEND = Transit('decl_send', 'Send', DRAFT, REVIEW, validators=['validator_must_active'])
ACCEPT = Transit('decl_accept', 'Accept', 'decl_review', 'decl_done', actions_after=['after_child_entities'])


def writes(queries) -> list[str]:
    return [
        it['sql'] for it in queries
        if it['sql'].lstrip().split(' ', 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE')
    ]


def errors(messages) -> list:
    return [it for it in messages if it.is_serious()]


@pytest.mark.django_db
def test_apply_is_idempotent_and_writes_nothing_again():
    changes = apply_declarations(workflows=[workflow(SEND, ACCEPT)])
    assert 'status decl_draft: created' in changes
    assert 'transit decl_send of entity.ParentEntity: created' in changes

    send = TransitModel.objects.get(pk='decl_send')
    assert (send.status_src_id, send.status_dst_id, send.validators) == ('decl_draft', 'decl_review', ['validator_must_active'])
    assert send.model_id == ContentType.objects.get_for_model(ParentEntity).pk
    assert TransitModel.objects.get(pk='decl_accept').actions_after == ['after_child_entities']
    # the names, translated into each column (the catalog of bazis-statusy translates Draft)
    draft = StatusModel.objects.get(pk='decl_draft')
    assert draft.name_en == 'Draft'
    assert {it.id for it in ParentEntity.get_model_transits()} >= {'decl_send', 'decl_accept'}

    with CaptureQueriesContext(connection) as queries:
        assert apply_declarations(workflows=[workflow(SEND, ACCEPT)]) == []
    assert writes(queries.captured_queries) == []


@pytest.mark.django_db
def test_a_changed_transit_is_updated_and_an_undeclared_one_kept():
    apply_declarations(workflows=[workflow(SEND, ACCEPT)])
    send = Transit('decl_send', 'Send it', DRAFT, DONE, actions_before=['before_dt_approved'])

    (change,) = apply_declarations(workflows=[workflow(send)])
    label, fields = change.removesuffix(' changed').split(': ')
    assert label == 'transit decl_send of entity.ParentEntity'
    assert set(fields.split(', ')) == {'name_en', 'name_ru', 'status_dst_id', 'validators', 'actions_before'}
    obj = TransitModel.objects.get(pk='decl_send')
    assert (obj.name_en, obj.status_dst_id, obj.validators, obj.actions_before) == (
        'Send it', 'decl_done', [], ['before_dt_approved'],
    )
    # its history references it: kept, and listed
    assert TransitModel.objects.filter(pk='decl_accept').exists()
    assert orphans(workflows=[workflow(send)]) == ['transit decl_accept of entity.ParentEntity']


@pytest.mark.django_db
def test_statuses_are_shared_by_the_models():
    # another workflow (of a model that has no statuses here) declares the same status
    same = Workflow('entity.ChildEntity', [Status('decl_draft', _('Draft'))], [])
    messages = declaration_messages([('a.workflow', workflow(SEND)), ('b.workflow', same)])
    assert not any('different names' in it.msg for it in messages)

    conflicting = Workflow('entity.ChildEntity', [Status('decl_draft', 'Brouillon')], [])
    messages = errors(declaration_messages([('a.workflow', workflow(SEND)), ('b.workflow', conflicting)]))
    assert any('The status decl_draft is declared with different names' in it.msg for it in messages)
    with pytest.raises(ImproperlyConfigured, match='statusy.E001'):
        apply_declarations(workflows=[workflow(SEND), conflicting])
    assert not StatusModel.objects.filter(pk='decl_draft').exists()


@pytest.mark.django_db
def test_a_transit_of_another_model_is_refused():
    StatusModel.objects.create(id='decl_draft', name_en='Draft')
    StatusModel.objects.create(id='decl_review', name_en='Review')
    TransitModel.objects.create(
        id='decl_send', model_id=ContentType.objects.get_for_model(ChildEntity).pk,
        status_src_id='decl_draft', status_dst_id='decl_review', name_en='Send',
    )
    with pytest.raises(ImproperlyConfigured, match='decl_send declared for entity.ParentEntity'):
        apply_declarations(workflows=[workflow(SEND)])

    # the database check reports it as an error, without failing
    conflicts = []
    changes = apply_declarations(workflows=[workflow(SEND)], dry_run=True, conflicts=conflicts)
    assert conflicts == [
        'The transit decl_send declared for entity.ParentEntity is a transit of another model '
        'in the database: rename it.'
    ]
    assert not any('decl_send' in it for it in changes)


@pytest.mark.django_db
def test_the_database_check_reports_a_transit_of_another_model(monkeypatch):
    monkeypatch.setattr(declare, 'declarations', lambda: [('entity.workflow', workflow(SEND))])
    apply_declarations()
    TransitModel.objects.filter(pk='decl_send').update(model_id=ContentType.objects.get_for_model(ChildEntity).pk)
    messages = check_declarations_applied(None, databases=['default'])
    assert [(it.id, it.is_serious()) for it in messages] == [('statusy.E004', True)]


@pytest.mark.django_db(transaction=True)
def test_flush_applies_them_again_with_the_new_content_types(monkeypatch):
    """
    `flush` (the end of every test with transaction=True) sends `post_migrate`: the
    content types are made again with other ids, the cached ones are forgotten and the
    declared transits reference the new ones.
    """
    monkeypatch.setattr(declare, 'declarations', lambda: [('entity.workflow', workflow(SEND, ACCEPT))])
    apply_declarations()
    old = StatusyContentType.objects.get_for_model(ParentEntity).pk

    call_command('flush', interactive=False, verbosity=0, reset_sequences=False)

    new = ContentType.objects.get_for_model(ParentEntity).pk
    assert new != old
    assert StatusyContentType.objects.get_for_model(ParentEntity).pk == new
    assert TransitModel.objects.get(pk='decl_send').model_id == new
    assert {it.id for it in ParentEntity.get_model_transits()} == {'decl_send', 'decl_accept'}


@pytest.mark.django_db
def test_post_migrate_skips_an_incomplete_migration_plan(monkeypatch):
    applied = []
    monkeypatch.setattr(declare, 'apply_declarations', lambda using: applied.append(using) or [])
    monkeypatch.setattr(declare, 'migrations_complete', lambda using: False)
    declare.post_migrate_apply(sender=None, using='default')
    assert applied == []


def test_post_migrate_skips_a_database_without_the_transits(monkeypatch):
    applied = []
    monkeypatch.setattr(declare, 'apply_declarations', lambda using: applied.append(using) or [])
    monkeypatch.setattr(declare.router, 'allow_migrate_model', lambda using, model: False)
    declare.post_migrate_apply(sender=None, using='other')
    assert applied == []


def test_the_checks_of_the_sample_pass():
    assert check_declarations(None) == []


@pytest.mark.parametrize(
    ('declared', 'problem'),
    [
        (Workflow('entity.Nothing', [DRAFT]), 'has no model entity.Nothing'),
        (Workflow('entity.ChildEntity', [DRAFT]), 'entity.ChildEntity of a workflow is not a StatusyMixin'),
        (workflow(Transit('decl_go', 'Go', DRAFT, 'decl_nowhere')), 'decl_nowhere, which is not a status'),
        (workflow(Transit('Decl Go', 'Go', DRAFT, REVIEW)), "The id 'Decl Go' of a transit"),
        (workflow(Transit('decl_go', '', DRAFT, REVIEW)), 'The transit decl_go of entity.ParentEntity has no name'),
        (workflow(SEND, statuses=[DRAFT, Status('decl.review', 'Review')]), "The id 'decl.review' of a status"),
    ],
)
def test_invalid_workflows(declared, problem):
    messages = errors(declaration_messages([('app.workflow', declared)]))
    assert {it.id for it in messages} == {'statusy.E001'}
    assert any(problem in it.msg for it in messages), [it.msg for it in messages]


def test_duplicates():
    messages = errors(declaration_messages([('a.workflow', workflow(SEND)), ('b.workflow', workflow(SEND))]))
    texts = [it.msg for it in messages]
    assert 'The workflow of entity.ParentEntity is declared more than once.' in texts
    assert any(it.startswith('The transit decl_send is declared more than once') for it in texts)


def test_a_missing_method():
    messages = errors(declaration_messages([('a.workflow', workflow(Transit('decl_go', 'Go', DRAFT, REVIEW, actions_before=['nothing'])))]))
    assert [it.id for it in messages] == ['statusy.E002']
    assert 'calls nothing, which is not a method of the model' in messages[0].msg


def test_the_transits_of_the_declared_permissions(monkeypatch):
    group = Group('decl_group', 'Group', [
        'entity.parent_entity.item.transit.all.decl_draft.decl_send',
        'entity.parent_entity.item.transit.all.all.decl_send',
        'entity.parent_entity.item.transit.all.decl_review.decl_send',
        'entity.parent_entity.item.transit.all.decl_draft.decl_missing',
        'entity.parent_entity.item.view.all.decl_review',
        'entity.parent_entity.item.change.author.decl_gone',
        'entity.parent_entity.field.view.all.decl_nothing.name.disable',
        'entity.parent_entity.field.view.all.all.name.disable',
    ])
    monkeypatch.setattr('bazis.contrib.permit.declare.declarations', lambda: ([('a.roles', group)], []))
    messages = errors(declaration_messages([('a.workflow', workflow(SEND))]))
    assert [it.id for it in messages] == ['statusy.E003'] * 4
    assert 'the transit decl_send starts from the status decl_draft, not decl_review' in messages[0].msg
    assert 'names the transit decl_missing, which is not declared for entity.parent_entity' in messages[1].msg
    assert 'item.change.author.decl_gone of the group decl_group names the status decl_gone' in messages[2].msg
    assert 'names the status decl_nothing, which is not a status of the workflow' in messages[3].msg


def test_untranslated_names_are_reported():
    messages = declaration_messages([('a.workflow', workflow(SEND))])
    (warning,) = [it for it in messages if it.id == 'statusy.W002']
    assert 'into ru: Draft, Review, Done, Send' in warning.msg


@pytest.mark.django_db
def test_the_database_checks(monkeypatch):
    monkeypatch.setattr(declare, 'declarations', lambda: [('entity.workflow', workflow(SEND))])
    assert [it.id for it in check_declarations_applied(None, databases=['default'])] == ['statusy.W003']
    apply_declarations()
    assert check_declarations_applied(None) == []
    assert check_declarations_applied(None, databases=['default']) == []

    TransitModel.objects.filter(pk='decl_send').update(validators=[])
    TransitModel.objects.create(
        id='decl_old', model=StatusyContentType.objects.get_for_model(ParentEntity),
        status_src_id='decl_draft', status_dst_id='decl_done', name_en='Old',
    )
    messages = check_declarations_applied(None, databases=['default'])
    assert [it.id for it in messages] == ['statusy.W003', 'statusy.W004']
    assert 'transit decl_send of entity.ParentEntity: validators changed' in messages[0].msg
    assert 'transit decl_old of entity.ParentEntity' in messages[1].msg
    assert TransitModel.objects.get(pk='decl_send').validators == []
