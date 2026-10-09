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

from django.core.checks import Tags, Warning, register


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
    methods (statusy.E001, statusy.E002), the transits of the declared permissions of
    bazis-permit (statusy.E003) and the translations of their names (statusy.W002).
    """
    from .declare import declaration_messages, declarations

    return declaration_messages(declarations())


@register(Tags.database)
def check_declarations_applied(app_configs, databases=None, **kwargs):
    """
    The database has the declared statuses and transits (statusy.W003) and no other transit
    of a model with a declared workflow (statusy.W004). Warnings: `migrate` runs the
    database checks before it applies the declarations. Skipped while migrations are not
    applied.
    """
    from bazis.contrib.permit.declare import migrations_complete

    from .declare import apply_declarations, declaration_messages, declarations, orphans

    workflows = declarations()
    if any(it.is_serious() for it in declaration_messages(workflows)):
        # statusy.E001 to statusy.E003
        return []
    messages = []
    for using in databases or ():
        if not migrations_complete(using):
            continue
        if changes := apply_declarations(using, workflows, dry_run=True):
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
