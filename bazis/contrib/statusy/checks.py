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
Django system checks of bazis-statusy (see `manage.py bazis_doctor`).
"""

from django.core.checks import Error, Tags, Warning, register


@register()
def check_routes_statusy(app_configs, **kwargs):
    """
    A JSON:API route of a StatusyMixin model that is not a StatusyRouteSetBase route has no
    transit endpoint and does not apply the permissions by status
    (`<app>.<model>.item.<operation>.<selector>.<status>`): only PermitStatusyService does.
    Runs when the application is loaded (`manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets

    if (app := loaded_app()) is None:
        return []

    from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

    from .models_abstract import StatusyMixin
    from .routes_abstract import StatusyRouteSetBase

    #: the actions that change an item (a read-only route needs no transitions)
    write_actions = {
        'action_create',
        'action_update',
        'action_post_relationships',
        'action_update_relationships',
        'action_delete_relationships',
    }

    return [
        Warning(
            f'The route {route_cls.__module__}.{route_cls.__qualname__} of the model '
            f'{route_cls.model._meta.label} with statuses does not support transitions.',
            hint=(
                'Inherit it from bazis.contrib.statusy.routes_abstract.StatusyRouteSetBase: '
                'it adds POST /{item_id}/transit/ and applies the permissions by status.'
            ),
            obj=route_cls,
            id='statusy.W001',
        )
        for route_cls, routes in route_sets(app).items()
        if issubclass(route_cls, JsonapiRouteBase)
        and any(route['action'] in write_actions for route in routes)
        and isinstance(getattr(route_cls, 'model', None), type)
        and issubclass(route_cls.model, StatusyMixin)
        and not issubclass(route_cls, StatusyRouteSetBase)
    ]


@register()
def check_declarations(app_configs, **kwargs):
    """
    The workflows declared in the `workflow.py` modules: their models, ids, statuses and
    methods (statusy.E001, statusy.E002) and the transits of the declared permissions of
    bazis-permit (statusy.E003). The translations of their names: `bazis_messages status`.
    """
    from .declare import declaration_messages, declarations

    return declaration_messages(declarations())


@register(Tags.database)
def check_declarations_applied(app_configs, databases=None, **kwargs):
    """
    The database has the declared statuses and transits (statusy.W003) and no other transit
    of a model with a declared workflow (statusy.W004): warnings, as `migrate` runs the
    database checks before it applies the declarations. A declared transit id that is a
    transit of another model is an error (statusy.E004): `migrate` could not apply it.
    Skipped while migrations are not applied.
    """
    from bazis.core.declare import migrations_complete

    from .declare import apply_declarations, declaration_messages, declarations, orphans

    workflows = declarations()
    if any(it.is_serious() for it in declaration_messages(workflows)):
        # statusy.E001 to statusy.E003
        return []
    messages = []
    for using in databases or ():
        if not migrations_complete(using):
            continue
        conflicts = []
        changes = apply_declarations(using, workflows, dry_run=True, conflicts=conflicts)
        messages.extend(
            Error(
                text,
                hint='Rename the declared transit, or the transit of the other model in the admin.',
                id='statusy.E004',
            )
            for text in conflicts
        )
        if changes:
            messages.append(
                Warning(
                    f'The database {using} differs from the declared workflows: {"; ".join(changes)}.',
                    hint='Run `manage.py migrate`: it applies the declarations.',
                    id='statusy.W003',
                )
            )
        if found := orphans(using, workflows):
            messages.append(
                Warning(
                    f'The database {using} has transits of models with a declared workflow that '
                    f'are not declared: {", ".join(found)}.',
                    hint=(
                        'Declare them, or delete them in the admin: deleting a transit deletes '
                        'its history (the transit facts of the objects).'
                    ),
                    id='statusy.W004',
                )
            )
    return messages


def _statusy_models() -> dict[tuple[str, str], type]:
    """
    The models with a status of their own (`StatusyMixin`, not the children whose status is
    their parent's) by the app and the resource name of their permissions.
    """
    from django.apps import apps

    from .models_abstract import StatusyMixin

    return {
        (model.get_resource_app(), model.get_resource_name()): model
        for model in apps.get_models()
        if issubclass(model, StatusyMixin)
    }


def _initial_status(model) -> str:
    """The status of a new object of the model created without one."""
    from django.conf import settings

    from .declare import initial_status

    return initial_status(model) or settings.BAZIS_STATUS_INITIAL[0]


def _routes_with_status(model) -> list[type]:
    """
    The registered route sets of the model whose create schema accepts `status` (the
    application must be loaded: `manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets
    from bazis.core.schemas import CrudApiAction

    if (app := loaded_app()) is None:
        return []
    found = []
    for route_cls, routes in route_sets(app).items():
        if getattr(route_cls, 'model', None) is not model or not any(
            it['action'] == 'action_create' for it in routes
        ):
            continue
        factory = route_cls.schema_factories.get(CrudApiAction.CREATE)
        if factory is not None and any(it.name == 'status' for it in factory.fields_list):
            found.append(route_cls)
    return found


def _status_hidden_on_create(label: str, slugs: set[str]) -> bool:
    """
    Whether the field permissions of add without a condition of the role
    (`<label>.field.add.all.all.<field>.<restriction>`) hide `status` from its create schema
    or make it read-only (a create ignores it): its own `disable` or `readonly` without
    `enable`, else those of `__all__`.
    """
    prefix = f'{label}.field.add.all.all.'
    restricts: dict[str, set[str]] = {}
    for slug in slugs:
        if slug.startswith(prefix) and len(rest := slug[len(prefix):].split('.', 1)) == 2:
            restricts.setdefault(rest[0], set()).update(rest[1].split('|'))
    for key in ('status', '__all__'):
        if own := restricts.get(key, set()) & {'enable', 'disable', 'readonly'}:
            return 'enable' not in own
    return False


def add_status_messages(
    roles: dict[str, set[str]], source: str, reported: dict[str, set[str]] | None = None
) -> list[Warning]:
    """
    The item permissions of add of the roles (`roles`: their slug → their permission
    slugs, from `source`) on the models with statuses. bazis-permit (2.11) checks the
    status of the created item against them, literally:

    - statusy.W005: none of the add permissions of a role on a model names its initial
      status (or `all`): a create without `status` is refused (403);
    - statusy.W006: `item.add.<selector>.all` while a route of the model accepts `status`
      on a create, unless the field permissions of add of the role hide it or make it
      read-only (`field.add.all.all.status.disable`): the role creates objects in any
      status, skipping the transits.

    `reported` (role → slugs) are the permissions another source reports (the declared
    ones, for the roles of the database): a message only about them is left out.
    """
    models = _statusy_models()
    reported = reported or {}
    messages = []
    for role, slugs in sorted(roles.items()):
        known = reported.get(role, set())
        # model → its add permissions of the role
        adds: dict[type, list[str]] = {}
        for slug in sorted(slugs):
            parts = slug.split('.')
            if len(parts) != 6 or parts[2:4] != ['item', 'add']:
                continue
            if (model := models.get((parts[0], parts[1]))) is not None:
                adds.setdefault(model, []).append(slug)
        for model, found in adds.items():
            label = f'{model.get_resource_app()}.{model.get_resource_name()}'
            initial = _initial_status(model)
            statuses = {it.rsplit('.', 1)[1] for it in found}
            if 'all' not in statuses and initial not in statuses and not set(found) <= known:
                messages.append(
                    Warning(
                        f'The role {role} ({source}) creates {label} only in the statuses '
                        f'{", ".join(sorted(statuses))} ({", ".join(found)}), not in its initial '
                        f'status {initial}: every create of the role without `status` is '
                        'refused (403).',
                        hint=(
                            f'If the role creates in {initial}, grant {label}.item.add.'
                            f'<selector>.{initial}; if it creates only in another status, its '
                            'client sends the status (the create schema of the route accepts it).'
                        ),
                        id='statusy.W005',
                    )
                )
            if 'all' not in statuses or _status_hidden_on_create(label, slugs):
                continue
            routes = _routes_with_status(model)
            for slug in found:
                if slug.rsplit('.', 1)[1] != 'all' or not routes or slug in known:
                    continue
                names = ', '.join(f'{it.__module__}.{it.__qualname__}' for it in routes)
                messages.append(
                    Warning(
                        f'The permission {slug} of the role {role} ({source}) creates {label} '
                        f'in any status: the create schema of {names} accepts `status`, so a '
                        'create skips the transits, their validators, actions and permissions.',
                        hint=(
                            f'Name the statuses the role creates in ({label}.item.add.<selector>.'
                            f'{initial}), hide the status from the creates of the role '
                            f'({label}.field.add.all.all.status.disable), or exclude it from the '
                            "create schema of the route (CrudApiAction.CREATE: "
                            "SchemaFields(exclude={'status': None}))."
                        ),
                        id='statusy.W006',
                    )
                )
    return messages


def _declared_roles() -> dict[str, set[str]]:
    """The roles declared in the `roles.py` modules (bazis-permit), with their permissions."""
    from bazis.contrib.permit.declare import Group, Role, declarations

    groups, roles = declarations()
    permissions = {it.slug: set(it.permissions) for _module, it in groups if isinstance(it, Group)}
    return {
        role.slug: set().union(*(permissions.get(it, set()) for it in role.groups))
        for _module, role in roles
        if isinstance(role, Role)
    }


@register()
def check_add_statuses(app_configs, **kwargs):
    """
    statusy.W005 and statusy.W006 for the roles declared in the `roles.py` modules of
    bazis-permit. statusy.W006 needs the loaded application (`manage.py bazis_doctor`).
    """
    return add_status_messages(_declared_roles(), 'roles.py')


@register(Tags.database)
def check_add_statuses_applied(app_configs, databases=None, **kwargs):
    """
    statusy.W005 and statusy.W006 for the roles of the database (made in the admin or the API,
    or a declared role with the groups the admin attached), with the permissions of all their
    groups; what only the declared permissions of a role cause is left to
    `check_add_statuses`. Skipped while migrations are not applied.
    """
    from django.apps import apps

    from bazis.core.declare import migrations_complete

    roles: dict[str, set[str]] = {}
    for using in databases or ():
        if not migrations_complete(using):
            continue
        for role, slug in (
            apps.get_model('permit.Role')
            .objects.using(using)
            .filter(groups_permission__permissions__slug__contains='.add.')
            .values_list('slug', 'groups_permission__permissions__slug')
            .distinct()
        ):
            roles.setdefault(role, set()).add(slug)
    return add_status_messages(roles, 'the database', reported=_declared_roles())
