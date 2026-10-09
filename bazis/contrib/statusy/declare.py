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
The statuses and transits of the models declared in the code of the applications.

An application declares them in `<app>/workflow.py`::

    from django.utils.translation import gettext_lazy as _
    from bazis.contrib.statusy.declare import Status, Transit, Workflow

    NEW, IN_PROGRESS = Status('new', _('New')), Status('in_progress', _('In progress'))
    WORKFLOWS = [
        Workflow('support.Ticket', [NEW, IN_PROGRESS], [
            Transit('take', _('Take'), NEW, IN_PROGRESS, actions_before=['before_take']),
        ]),
    ]

After `migrate` (the `post_migrate` signal, once the migrations of the project are all
applied) the database has them, in one transaction: the statuses (shared by the models: a
status declared by several workflows has one name) and the transits of the declared
models are created or updated as declared. A status is never deleted (the objects in it
would be); a transit of a declared model that is not declared is kept, as its history
references it (the database check warns). The names are English msgids, translated into
each `name_<language>` column by the catalogs of the project.
"""

import logging
import re
import sys
from dataclasses import dataclass

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.checks import CheckMessage, Error, Warning
from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, router, transaction
from django.utils import translation
from django.utils.functional import Promise

from bazis.contrib.permit.declare import discover, migrations_complete, translations, untranslated


logger = logging.getLogger(__name__)

#: the id of a declared status or transit: a segment of the permission slugs
ID = re.compile(r'^[a-z0-9_-]+$')


@dataclass(frozen=True)
class Status:
    """
    A status: its id and its English name (`gettext_lazy`).
    """

    id: str
    name: str | Promise


@dataclass(frozen=True)
class Transit:
    """
    A transit of a model from the status `src` to `dst` (statuses or their ids), with the
    methods of the model that validate it and act before and after it.
    """

    id: str
    name: str | Promise
    src: str
    dst: str
    validators: tuple[str, ...] = ()
    actions_before: tuple[str, ...] = ()
    actions_after: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('src', 'dst'):
            if isinstance(value := getattr(self, name), Status):
                object.__setattr__(self, name, value.id)
        for name in ('validators', 'actions_before', 'actions_after'):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class Workflow:
    """
    The statuses and the transits of a model (`app_label.Model` or the class).
    """

    model: str | type
    statuses: tuple[Status, ...] = ()
    transits: tuple[Transit, ...] = ()

    def __post_init__(self):
        if isinstance(self.model, type):
            object.__setattr__(self, 'model', self.model._meta.label)
        object.__setattr__(self, 'statuses', tuple(self.statuses))
        object.__setattr__(self, 'transits', tuple(self.transits))


def declarations() -> list[tuple[str, Workflow]]:
    """
    The workflows (WORKFLOWS) of the `workflow.py` modules of the applications, with their
    module.
    """
    return discover('workflow', 'WORKFLOWS')


def _model(label: str):
    try:
        return apps.get_model(label)
    except (LookupError, ValueError):
        return None


def _source(text) -> str:
    with translation.override(None):
        return str(text)


def _workflow_messages(module: str, workflow: Workflow, error) -> None:  # noqa: C901
    from .models_abstract import StatusyMixin

    model = _model(workflow.model)
    if model is None:
        error(f'The workflow of {module} has no model {workflow.model}.', module, id='statusy.E001')
    elif not issubclass(model, StatusyMixin):
        error(f'The model {workflow.model} of a workflow is not a StatusyMixin.', module, id='statusy.E001')
        model = None

    statuses = {status.id for status in workflow.statuses if isinstance(status, Status)}
    for it in (*workflow.statuses, *workflow.transits):
        kind = type(it).__name__.lower()
        if not isinstance(it, (Status, Transit)):
            error(f'{it!r} of the workflow of {workflow.model} is not a Status or a Transit.', module, id='statusy.E001')
            continue
        if not isinstance(it.id, str) or not ID.match(it.id):
            error(
                f'The id {it.id!r} of a {kind} of {workflow.model} is invalid.', module,
                hint='Lowercase letters, digits, "_" and "-": it is a segment of the permissions.',
                id='statusy.E001',
            )
        if not isinstance(it.name, (str, Promise)) or not str(it.name):
            error(f'The {kind} {it.id} of {workflow.model} has no name.', module, id='statusy.E001')

    for transit in workflow.transits:
        if not isinstance(transit, Transit):
            continue
        for status in (transit.src, transit.dst):
            if status not in statuses:
                error(
                    f'The transit {transit.id} of {workflow.model} goes from or to the status '
                    f'{status}, which is not a status of the workflow.', module, id='statusy.E001',
                )
        if model is None:
            continue
        for name in (*transit.validators, *transit.actions_before, *transit.actions_after):
            if not callable(getattr(model, name, None)):
                error(
                    f'The transit {transit.id} of {workflow.model} calls {name}, which is not a '
                    f'method of the model.', module, id='statusy.E002',
                )


def _permission_messages(workflows: list[tuple[str, Workflow]], error) -> None:
    """
    The transits of the declared permissions (bazis-permit) of the models with a declared
    workflow: `<app>.<model>.item.transit.<selector>.<status>.<transit>`.
    """
    from bazis.contrib.permit.declare import declarations as permit_declarations

    transits = {}
    for _module, workflow in workflows:
        if (model := _model(workflow.model)) is not None and hasattr(model, 'get_resource_name'):
            key = (model.get_resource_app(), model.get_resource_name())
            transits[key] = {it.id: it for it in workflow.transits if isinstance(it, Transit)}

    groups, _roles = permit_declarations()
    for module, group in groups:
        for slug in getattr(group, 'permissions', ()):
            parts = slug.split('.')
            if len(parts) != 7 or parts[2:4] != ['item', 'transit']:
                continue
            if (declared := transits.get((parts[0], parts[1]))) is None:
                continue
            status, transit_id = parts[5], parts[6]
            if (transit := declared.get(transit_id)) is None:
                error(
                    f'The permission {slug} of the group {group.slug} names the transit '
                    f'{transit_id}, which is not declared for {parts[0]}.{parts[1]}.', module,
                    id='statusy.E003',
                )
            elif status not in ('all', transit.src):
                error(
                    f'The permission {slug} of the group {group.slug}: the transit {transit_id} '
                    f'starts from the status {transit.src}, not {status}.', module, id='statusy.E003',
                )


def _duplicate_messages(models: dict, statuses: dict, transits: dict, error) -> None:
    for label, modules in models.items():
        if len(modules) > 1:
            error(f'The workflow of {label} is declared more than once.', ', '.join(modules), id='statusy.E001')
    for status_id, names in statuses.items():
        if len(names) > 1:
            error(
                f'The status {status_id} is declared with different names: {", ".join(names)}.',
                ', '.join(sorted({it for found in names.values() for it in found})),
                hint='The statuses are shared by the models: give it one name.', id='statusy.E001',
            )
    for transit_id, found in transits.items():
        if len(found) > 1:
            error(
                f'The transit {transit_id} is declared more than once: {", ".join(found)}.',
                found[0], hint='The id of a transit is unique among all the models.', id='statusy.E001',
            )


def declaration_messages(workflows: list[tuple[str, Workflow]]) -> list[CheckMessage]:
    """
    The problems of the declarations (statusy.E001 to statusy.E003, statusy.W002);
    `apply_declarations` refuses declarations with errors.
    """
    messages = []

    def error(text, module, hint=None, *, id):  # the id of the check
        messages.append(Error(text, hint=hint, obj=module, id=id))

    models, statuses, transits = {}, {}, {}
    for module, workflow in workflows:
        if not isinstance(workflow, Workflow):
            error(f'{workflow!r} of {module} is not a Workflow.', module, id='statusy.E001')
            continue
        models.setdefault(workflow.model, []).append(module)
        for status in workflow.statuses:
            if isinstance(status, Status):
                statuses.setdefault(status.id, {}).setdefault(_source(status.name), []).append(module)
        for transit in workflow.transits:
            if isinstance(transit, Transit):
                transits.setdefault(transit.id, []).append(f'{workflow.model} ({module})')
        _workflow_messages(module, workflow, error)

    _duplicate_messages(models, statuses, transits, error)

    if apps.is_installed('bazis.contrib.permit'):
        _permission_messages(workflows, error)

    names = [
        it.name for _module, workflow in workflows if isinstance(workflow, Workflow)
        for it in (*workflow.statuses, *workflow.transits)
        if isinstance(it, (Status, Transit)) and isinstance(it.name, (str, Promise)) and str(it.name)
    ]
    for language, missing in untranslated(list(dict.fromkeys(names))).items():
        messages.append(
            Warning(
                f'The names of declared statuses or transits have no translation into '
                f'{language}: {", ".join(dict.fromkeys(missing))}.',
                hint='Translate them in the locale of the project (makemessages, compilemessages).',
                id='statusy.W002',
            )
        )
    return messages


def _changed(obj, values: dict) -> list[str]:
    return [name for name, value in values.items() if getattr(obj, name) != value]


def _content_types():
    """
    The cached content types are forgotten: `flush` creates them again with other ids.
    """
    ContentType.objects.clear_cache()
    apps.get_model('statusy.StatusyContentType').objects.clear_cache()


def apply_declarations(
    using: str = DEFAULT_DB_ALIAS, workflows=None, dry_run: bool = False
) -> list[str]:
    """
    Applies the declared workflows (by default those of the `workflow.py` modules) to the
    database in one transaction and returns the changes; with `dry_run` only returns them.
    Applied again, it writes nothing. A transit id of another model is an error.
    """
    if workflows is None:
        workflows = declarations()
    workflows = [it if isinstance(it, tuple) else ('', it) for it in workflows]
    if errors := [it for it in declaration_messages(workflows) if it.is_serious()]:
        raise ImproperlyConfigured(
            'Invalid declarations of workflows:\n' + '\n'.join(f'{it.id}: {it.msg}' for it in errors)
        )

    status_model = apps.get_model('statusy.Status')
    transit_model = apps.get_model('statusy.Transit')
    changes = []

    def sync(model, pk: str, obj, label: str, values: dict) -> None:
        if obj is None:
            changes.append(f'{label}: created')
            obj, changed, update_fields = model(pk=pk), list(values), None
        elif changed := _changed(obj, values):
            changes.append(f'{label}: {", ".join(changed)} changed')
            update_fields = changed
        else:
            return
        if not dry_run:
            for name in changed:
                setattr(obj, name, values[name])
            obj.save(using=using, update_fields=update_fields)

    _content_types()
    with transaction.atomic(using=using):
        statuses = {status.id: status for _module, workflow in workflows for status in workflow.statuses}
        existing = status_model.objects.using(using).in_bulk(list(statuses))
        for status_id, status in statuses.items():
            sync(status_model, status_id, existing.get(status_id), f'status {status_id}', translations(status.name))

        content_types = ContentType.objects.db_manager(using)
        for _module, workflow in workflows:
            model = apps.get_model(workflow.model)
            if dry_run:
                # get_for_model would create a missing one
                content_type = content_types.filter(
                    app_label=model._meta.app_label, model=model._meta.model_name
                ).first()
            else:
                content_type = content_types.get_for_model(model)
            existing = transit_model.objects.using(using).in_bulk([it.id for it in workflow.transits])
            for transit in workflow.transits:
                obj = existing.get(transit.id)
                if obj is not None and content_type is not None and obj.model_id != content_type.pk:
                    raise ImproperlyConfigured(
                        f'The transit {transit.id} declared for {workflow.model} is a transit of '
                        f'another model in the database: rename it.'
                    )
                values = {
                    **translations(transit.name),
                    'model_id': content_type.pk if content_type else None,
                    'status_src_id': transit.src,
                    'status_dst_id': transit.dst,
                    'validators': list(transit.validators),
                    'actions_before': list(transit.actions_before),
                    'actions_after': list(transit.actions_after),
                }
                sync(transit_model, transit.id, obj, f'transit {transit.id} of {workflow.model}', values)
    return changes


def orphans(using: str = DEFAULT_DB_ALIAS, workflows=None) -> list[str]:
    """
    The transits of the database of the models with a declared workflow that are not
    declared.
    """
    if workflows is None:
        workflows = declarations()
    found = []
    transit_model = apps.get_model('statusy.Transit')
    for workflow in (it[1] if isinstance(it, tuple) else it for it in workflows):
        model = apps.get_model(workflow.model)
        content_type = ContentType.objects.db_manager(using).filter(
            app_label=model._meta.app_label, model=model._meta.model_name
        ).first()
        if content_type is None:
            continue
        found.extend(
            f'transit {it} of {workflow.model}'
            for it in transit_model.objects.using(using).filter(model_id=content_type.pk)
            .exclude(pk__in=[transit.id for transit in workflow.transits])
            .order_by('pk').values_list('pk', flat=True)
        )
    return found


def post_migrate_apply(sender, using=DEFAULT_DB_ALIAS, verbosity=1, **kwargs):
    """
    The receiver of `post_migrate` (also sent by `flush`): applies the declarations once
    the migrations of the project are all applied.
    """
    if not router.allow_migrate_model(using, apps.get_model('statusy.Transit')):
        return
    if not migrations_complete(using):
        logger.info('Not all the migrations are applied: the declared workflows are not applied.')
        return
    changes = apply_declarations(using)
    stdout = kwargs.get('stdout') or sys.stdout
    if changes and verbosity >= 1:
        stdout.write(f'  Applied the declared workflows: {len(changes)} change(s)\n')
    if verbosity >= 2:
        for change in changes:
            stdout.write(f'    {change}\n')
