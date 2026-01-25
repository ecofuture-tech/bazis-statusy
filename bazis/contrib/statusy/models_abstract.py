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

import traceback
from itertools import chain
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentTypeManager
from django.contrib.postgres.fields import ArrayField
from django.db import connections, models, transaction
from django.db.utils import ProgrammingError
from django.utils.functional import cached_property
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

from pydantic import BaseModel, ValidationError

from translated_fields import TranslatedFieldWithFallback, to_attribute

from bazis.contrib.permit.models_abstract import PermitModelMixin
from bazis.core.errors import JsonApiBazisException
from bazis.core.models_abstract import InitialBase, JsonApiMixin, logger
from bazis.core.utils.functools import get_func_sig_param
from bazis.core.utils.orm import AbstractForeignKey

from . import TransitError
from .schemas import StatusyApiAction, payload_validate_none


if TYPE_CHECKING:
    from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase

    User = get_user_model()


def status_default():
    """Getting the default status (from settings),
    which will be set for the model if the model has StatusyMixin
    """
    related_model = StatusyMixin.get_fields_info().relations['status'].related_model
    if isinstance(related_model, str):
        related_model = apps.get_model(related_model)
    status_initial = related_model.get_status_initial()
    if status_initial:
        return status_initial.pk
    return settings.BAZIS_STATUS_INITIAL[0]


class StatusyContentTypeManager(ContentTypeManager):
    """
    Manager for working only with status models
    """
    def get_queryset(self):
        qs = super().get_queryset()

        # Save the result in cache for performance
        if not hasattr(self, '_statusy_content_types'):
            try:
                # Check that the model system is ready
                if not apps.models_ready:
                    return qs

                # Deferred computation with a lazy collection
                from django.db.models import Q

                query = Q(pk=None)  # Empty query
                for app_config in apps.get_app_configs():
                    for model in app_config.get_models():
                        if issubclass(model, StatusyMixin):
                            query |= Q(
                                app_label=model._meta.app_label,
                                model=model._meta.model_name
                            )

                self._statusy_content_types = query
            except (ProgrammingError, ImportError, RuntimeError):
                # If the DB is not ready or other errors occur
                return qs

        # Apply the filter only if it was successfully created
        if hasattr(self, '_statusy_content_types'):
            return qs.filter(self._statusy_content_types)
        return qs
    #
    #
    # def get_queryset(self):
    #     qs = super().get_queryset()
    #
    #     # Get all models inheriting StatusyMixin
    #     statusy_models = []
    #     for app_config in apps.get_app_configs():
    #         for model in app_config.get_models():
    #             if issubclass(model, StatusyMixin):
    #                 statusy_models.append(model)
    #
    #     # Filter ContentType only for these models
    #     return qs.filter(
    #         app_label__in=[model._meta.app_label for model in statusy_models],
    #         model__in=[model._meta.model_name for model in statusy_models]
    #     )
    #
    #     def gen_content_types():
    #         try:
    #             for c_type in ContentType.objects.all():
    #                 model_class = c_type.model_class()
    #                 if model_class and issubclass(model_class, StatusyMixin):
    #                     yield c_type.id
    #         except ProgrammingError:
    #             pass
    #
    #     return super().get_queryset().filter(id__in=list(gen_content_types()))


class StatusyContentTypeMixin(InitialBase):
    """
    Model for working only with status models
    """

    class Meta:
        abstract = True
        verbose_name = _('Status model')
        verbose_name_plural = _('Status models')

    objects = StatusyContentTypeManager()

    def __str__(self):
        model = self.model_class()
        if not model:
            return 'MODEL NOT FOUND'
        return f'{apps.get_app_config(model._meta.app_label).verbose_name} > {model._meta.verbose_name}'


class StatusBase(JsonApiMixin):
    id = models.CharField(_('Label'), max_length=255, primary_key=True)
    name = TranslatedFieldWithFallback(models.CharField(_('Name'), max_length=255, default='', blank=True))

    class Meta:
        abstract = True
        verbose_name = _('Status')
        verbose_name_plural = _('Statuses')

    def __str__(self):
        return self.name or str(self.id)

    @classmethod
    def get_id_example(cls):
        return settings.BAZIS_STATUS_INITIAL[0]

    @classmethod
    def get_status_initial(cls):
        # """Getting the default status (from settings),
        #    which will be set for the model if the model has StatusyMixin
        #    In tests we have an issue that route initialization also touches
        #    this method, which causes an error because the query goes to the DB, and the DB is not ready,
        #    to check this just run a test with a model that uses StatusyMixin
        #    and when importing routes from main.py we will get an error
        #    RuntimeError: Database access not allowed, use the "django_db" mark ...
        # """
        try:
            for conn in connections.all(initialized_only=True)[:1]:
                conn.cursor().execute('select 1')
        except Exception as e:
            traceback.print_exc()
            logger.info(f"""
            get_status_initial raise exception with not ready db connection {e}\n
            if you run test - do not worry about this message, otherwise - it is PROBLEM!
            """)
            return None
        try:
            table = cls._meta.db_table
            column = to_attribute('name')
            for conn in connections.all(initialized_only=True)[:1]:
                if table not in conn.introspection.table_names():
                    return None
                with conn.cursor() as cursor:
                    columns = {col.name for col in conn.introspection.get_table_description(cursor, table)}
                if column not in columns:
                    logger.info('statusy_status columns not ready; skip default status creation')
                    return None
            return cls.objects.get_or_create(id=settings.BAZIS_STATUS_INITIAL[0], defaults={
                column: settings.BAZIS_STATUS_INITIAL[1]
            })[0]
        except ProgrammingError as e:
            message = str(e)
            if '"statusy_status"' in message:
                return cls(id=settings.BAZIS_STATUS_INITIAL[0], **{
                    to_attribute('name', settings.LANGUAGE_CODE): settings.BAZIS_STATUS_INITIAL[1]
                })
            raise e

class TransitRelationManager(models.Manager):
    def get_by_natural_key(self, transit_parent, transit_child, item_selector):
        return self.get(
            transit_parent=transit_parent, transit_child=transit_child, item_selector=item_selector
        )


class TransitRelationBase(JsonApiMixin):
    transit_parent = models.ForeignKey(
        settings.BAZIS_STATUSY_TRANSIT_MODEL,
        related_name='transit_relations_as_parent',
        on_delete=models.CASCADE,
    )
    transit_child = models.ForeignKey(
        settings.BAZIS_STATUSY_TRANSIT_MODEL,
        related_name='transit_relations_as_child',
        on_delete=models.CASCADE,
    )
    item_selector = models.CharField(
        _('Object access selector for child transition'), max_length=255
    )

    objects = TransitRelationManager()

    def natural_key(self):
        return (self.transit_parent, self.transit_child, self.item_selector)

    natural_key.dependencies = ['statusy.transit']

    class Meta:
        abstract = True
        verbose_name = _('Transit relation')
        verbose_name_plural = _('Transit relations')


class TransitBase(JsonApiMixin):
    id = models.CharField(_('Label'), max_length=255, primary_key=True)
    name = TranslatedFieldWithFallback(models.CharField(_('Name'), max_length=255, default='', blank=True))
    model = models.ForeignKey('statusy.StatusyContentType', related_name='transits', on_delete=models.CASCADE)
    status_src = models.ForeignKey(
        settings.BAZIS_STATUSY_STATUS_MODEL,
        verbose_name=_('Initial status'),
        related_name='transit_src',
        on_delete=models.CASCADE,
    )
    status_dst = models.ForeignKey(
        settings.BAZIS_STATUSY_STATUS_MODEL,
        verbose_name=_('Destination status'),
        related_name='transit_dst',
        on_delete=models.CASCADE,
    )
    source_link = models.CharField(_('Transit link in code'), max_length=255, null=True, blank=True)
    validators = ArrayField(
        models.CharField(max_length=255),
        verbose_name=_('Transit validators'),
        default=list,
        blank=True,
    )
    actions_before = ArrayField(
        models.CharField(max_length=255),
        verbose_name=_('Actions before transit'),
        default=list,
        blank=True,
    )
    actions_after = ArrayField(
        models.CharField(max_length=255),
        verbose_name=_('Actions after transit'),
        default=list,
        blank=True,
    )
    is_schema_validate = models.BooleanField(
        _('Validate current status data during transition'),
        default=True,
    )
    transits_related = models.ManyToManyField(
        'self',
        verbose_name=_('Related transits'),
        blank=True,
        through=settings.BAZIS_STATUSY_TRANSIT_RELATION_MODEL,
        through_fields=('transit_parent', 'transit_child'),
    )
    hint = models.TextField(_('Note'), null=True, blank=True)
    hint_title = TranslatedFieldWithFallback(models.CharField(_('Note title'), max_length=255, null=True, blank=True))
    hint_action = models.TextField(_('Note action'), null=True, blank=True)

    class Meta:
        abstract = True
        verbose_name = _('Transit')
        verbose_name_plural = _('Transits')

    def __str__(self):
        return f'{self.name} ({self.id}) [{self.model}]'

    @classmethod
    def get_id_example(cls):
        return 'accept'

    def save(self, force_insert=False, force_update=True, *args, **kwargs):
        if not self.id:
            # base of id
            id_base = f'{self.model.model}#{self.status_src.pk}_to_{self.status_dst.pk}'
            # set of existing ids
            ids = set(
                type(self).objects.filter(id__istartswith=self.id).values_list('id', flat=True)
            )

            self.id = id_base

            counter = 1
            while self.id in ids:
                self.id = f'{id_base}#{counter}'
                counter += 1

        super().save(*args, **kwargs)


class StatusyMixin(PermitModelMixin, JsonApiMixin):
    """
    Mixin that implements the logic of adding statuses and switching them.
    For an entity of such a model, transition functionality is available.
    """

    status = models.ForeignKey(
        settings.BAZIS_STATUSY_STATUS_MODEL,
        verbose_name=_('Current status'),
        on_delete=models.CASCADE,
        default=status_default,
    )
    status_dt = models.DateTimeField(_('Status timestamp'), auto_now_add=True)
    status_author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='status_author_%(class)s',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    # auto-filled dictionary of the form: child model -> path to the parent field in the child entity
    _statusy_children_models_dict: dict[type['StatusyChildMixin'], str] = {}

    class Meta:
        abstract = True

    @cached_property
    def statusy_children_items(self) -> list[JsonApiMixin]:
        for child_model, field_path in self._statusy_children_models_dict.items():
            yield from child_model.objects.filter(**{field_path: self})

    @classmethod
    def get_status_field(cls):
        return 'status_id'

    @classmethod
    def get_model_transits(cls) -> list[TransitBase]:
        """
        Allowed transitions for the model
        """
        return apps.get_model('statusy.StatusyContentType').objects.get_for_model(cls).transits.select_related(
            'status_src', 'status_dst'
        )

    @classmethod
    def get_model_statuses(cls) -> list[str]:
        """
        Allowed statuses for the model
        """
        return list(
            set(
                chain(
                    *[
                        [transit.status_src_id, transit.status_dst_id]
                        for transit in cls.get_model_transits()
                    ]
                )
            )
        )

    @property
    def instance_transits(self) -> list[TransitBase]:
        """
        :return: List of all available transitions for the object in its current status.
        """
        return [
            transit for transit in self.get_model_transits() if transit.status_src == self.status
        ]

    def get_transit(self, label) -> TransitBase | None:
        """
        :param label: Transition label
        :return: Specific transition
        """
        return ([transit for transit in self.instance_transits if transit.id == label] + [None])[0]

    def transit_payload_type(self, transit: TransitBase) -> type[BaseModel] | None:
        """
        Build a combined schema for the payload for the transition
        :param transit:
        :return:
        """
        payload_types = []
        for action_name in transit.validators + transit.actions_before + transit.actions_after:
            if action_func := getattr(self, action_name, None):
                if callable(action_func):
                    if payload_param := get_func_sig_param(action_func, 'payload'):
                        payload_type = payload_param.annotation

                        if payload_type is not payload_param.empty:
                            # if a custom dynamic schema builder is specified - use it
                            if hasattr(payload_type, 'schema_build'):
                                payload_type = payload_type.schema_build(transit)
                            payload_types.append(payload_type)

        if not payload_types:
            return

        # deduplicate types
        payload_types = tuple(set(payload_types))
        payload_types_names = sorted([str(id(cl)) for cl in payload_types])
        # return the resulting class
        return type('PayloadType_' + ''.join(payload_types_names), payload_types, {})

    def schema_validate(self, route_cls: type['StatusyRouteSetBase'], user: 'User'):
        from .routes_abstract import SchemasStatusyPermit

        schemas = SchemasStatusyPermit(route_cls, user, self)
        schemas[StatusyApiAction.TRANSIT].model_validate(self)

        # validate all child entities
        for child_item in self.statusy_children_items:
            child_model = child_item.__class__
            child_route = route_cls._routes_child_dict.get(
                child_model, child_model.get_default_route()
            )
            child_schemas = SchemasStatusyPermit(child_route, user, child_item)
            # perform validation
            child_schemas[StatusyApiAction.TRANSIT].model_validate(child_item)

    def transit_validation(self, transit: TransitBase, user, payload: dict | None) -> Any: # noqa: C901
        """
        Checks whether the transition is allowed. If any errors are found, an exception will be raised with their list.

        :param transit: bazis.contrib.statusy.models.Transit
        :param user: current user object (AUTH_USER_MODEL or None)
        :param payload: transition data dictionary or None
        :return: Payload object created from the passed payload dictionary
        """
        payload_obj = None
        errors = []

        # check for dependent transitions
        # get the list of child transitions
        # transit_children = TransitRelation.objects.filter(transit_parent=transit).all()

        # # if the transition has descendants - check that all related objects have changed their status
        # for child in transit_children:
        #     # extract the object by selector
        #     if item := get_attr(self, child.item_selector):
        #         if item.status != child.transit_child.status_dst:
        #             errors.append(TransitError(
        #                 _('Transition `%s` is not executed') % child.transit_child.name,
        #                 code='TRANSIT_RELATED_REQUIRED',
        #                 meta_data=item.resource_id,
        #                 item=item
        #             ))

        # check whether this transition is allowed for the model
        if not isinstance(self, transit.model.model_class()):
            raise JsonApiBazisException(
                TransitError(
                    _('The specified transition is not available for objects of this type'),
                    item=self,
                )
            )

        # if payload content validation is required - perform it
        if payload is not payload_validate_none:
            if payload_type := self.transit_payload_type(transit):
                if payload is None:
                    raise JsonApiBazisException(
                        TransitError(_('This transition requires a payload'), item=self)
                    )
                try:
                    payload_obj = payload_type.model_validate(payload)
                except ValidationError as e:
                    errors.extend(
                        JsonApiBazisException.from_validation_error(
                            e, loc=('payload',), item=self
                        ).errors
                    )
                    raise JsonApiBazisException(errors, status=HTTP_422_UNPROCESSABLE_ENTITY) from e
        else:
            payload_obj = payload_validate_none

        # perform custom transition validation
        for validator_name in transit.validators:
            if validator := getattr(self, validator_name, None):
                if callable(validator):
                    try:
                        validator(transit, user, payload_obj)
                    except TransitError as e:
                        errors.append(e)
                    except JsonApiBazisException as e:
                        for err in e.errors:
                            if not err.item:
                                err.item = self
                        errors.extend(e.errors)
                    except ValidationError as e:
                        errors_validation = JsonApiBazisException.from_validation_error(e).errors
                        for err in errors_validation:
                            if not err.item:
                                err.item = self
                        errors.extend(errors_validation)
        if errors:
            raise JsonApiBazisException(errors, status=HTTP_422_UNPROCESSABLE_ENTITY)

        return payload_obj

    def transit_apply(
        self, transit: TransitBase, user=None, payload: dict = None
    ) -> 'StatusyMixin':
        """
        Executes the transition:

        - Look up the transition settings for the current model.
        - Perform validation:
          - Methods of the current class declared as validators are called.
          - Validator signature: (transit, user, payload).
        - A transition object is created.
        - Pre-actions are executed that must return the current version of the current object:
          - Methods of the current class declared as "action before transition" are called.
          - Signature: (statusy_transit, payload).
        - The transition object is activated, setting the corresponding fields.

        :param transit: Transition object.
        :param user: User performing the transition.
        :param payload: Dictionary of additional transition data. Will be processed in a custom class.
        :return: Returns the object to which the transition was applied after all pre-processing.
        """
        # perform transition validation, obtaining the payload object (may be None)
        payload_obj = self.transit_validation(transit, user, payload)

        # reference to the current instance
        instance = self

        with transaction.atomic(savepoint=False):
            # create the actual transition object in the context of the current object
            statusy_transit = self.create_statusy_transit(transit, user)

            # execute custom "before" logic
            for action_name in transit.actions_before:
                if action := getattr(instance, action_name, None):
                    if callable(action):
                        if new_instance := action(statusy_transit, payload_obj):
                            instance = new_instance

            # set status
            statusy_transit.status_apply()

            # execute custom "after" logic
            for action_name in transit.actions_after:
                if action := getattr(instance, action_name, None):
                    if callable(action):
                        action(statusy_transit, payload_obj)

            instance.refresh_from_db()
            return instance

    # set object status
    def create_statusy_transit(self, transit: TransitBase, author):
        return self.statusy_transits.create(
            transit=transit,
            status=transit.status_dst,
            dt=now(),
            author=author,
        )


class StatusyChildMixin(JsonApiMixin):
    statusy_model: type[StatusyMixin] = None

    class Meta:
        abstract = True

    @classmethod
    def get_status_field(cls):
        """
        The method must be defined in the child class to explicitly specify the field that will be used
        as the path to the status.
        """
        raise NotImplementedError('You must define "get_status_field" method in child class')

    @classmethod
    def _statusy_register(cls):
        """
        The method registers the child status class.
        Initialization of the registration occurs after all models are ready in .apps.StatusyConfig.ready
        """
        if cls._meta.abstract:
            return

        # parse the reference to the status field
        status_path = cls.get_status_field().split('__')
        parent_path = []

        parent_model = cls
        for s_field_name in status_path:
            if field_info := parent_model.get_fields_info().relations.get(s_field_name):
                parent_model = field_info.related_model
                parent_path.append(s_field_name)

        if not issubclass(parent_model, StatusyMixin):
            raise TypeError('"statusy_model" must be a subclass of StatusyMixin')

        # perform cross-assignment of status models and child structures
        cls.statusy_model = parent_model
        if not parent_model._statusy_children_models_dict:
            parent_model._statusy_children_models_dict = {}
        parent_model._statusy_children_models_dict[cls] = '__'.join(parent_path)


class StatusyTransit(InitialBase):
    transit = models.ForeignKey(
        settings.BAZIS_STATUSY_TRANSIT_MODEL, related_name='+', on_delete=models.CASCADE
    )
    status = models.ForeignKey(
        settings.BAZIS_STATUSY_STATUS_MODEL, related_name='+', on_delete=models.CASCADE
    )
    dt = models.DateTimeField(_('Status timestamp'), auto_now_add=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='status_author_%(class)s',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    extra = models.JSONField(_('Transit extra data'), default=dict)
    statusy_item = AbstractForeignKey(
        StatusyMixin,
        class_abstract_path=settings.BAZIS_STATUSY_TRANSIT_MIDDLE_ABSTRACT_MODEL,
        related_name='statusy_transits'
    )

    class Meta:
        abstract = True
        verbose_name = _('Transit fact')
        verbose_name_plural = _('Transit facts')

    # set object status
    def status_apply(self):
        self.statusy_item.status = self.status
        self.statusy_item.status_dt = self.dt
        self.statusy_item.status_author = self.author
        self.statusy_item.save()
