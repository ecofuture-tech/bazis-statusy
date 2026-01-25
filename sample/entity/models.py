from django.db import models
from django.utils.translation import gettext_lazy as _

from bazis_test_utils.models_abstract import (
    ChildEntityBase,
    DependentEntityBase,
    ExtendedEntityBase,
    ParentEntityBase,
)

from bazis.contrib.author.models_abstract import AuthorMixin
from bazis.contrib.statusy import TransitError, transit_after, transit_before, transit_validator
from bazis.contrib.statusy.models_abstract import (
    StatusyChildMixin,
    StatusyMixin,
    StatusyTransit,
    TransitBase,
)
from bazis.contrib.users import get_user_model
from bazis.core.models_abstract import DtMixin, JsonApiMixin, UuidMixin
from bazis.core.triggers import FieldsTransferTrigger, FieldTransferSchema
from bazis.core.utils import triggers as bazis_triggers

from .schemas import ParentEntityBeforeSchema, ParentEntityValidatedSchema


User = get_user_model()


@bazis_triggers.register(
    FieldsTransferTrigger(
        related_field='parent_entities',
        fields={
            'author_parent': FieldTransferSchema(
                source='author',
            ),
        },
    )
)
class ChildEntity(
    StatusyChildMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, ChildEntityBase
):
    author_parent = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)

    @classmethod
    def get_status_field(cls):
        return 'parent_entities__status_id'

    class Meta:
        verbose_name = _('Child entity')
        verbose_name_plural = _('Child entities')


@bazis_triggers.register(
    FieldsTransferTrigger(
        related_field='parent_entity',
        fields={
            'author_parent': FieldTransferSchema(
                source='author',
            ),
        },
    )
)
class DependentEntity(
    StatusyChildMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, DependentEntityBase
):
    author_parent = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    parent_entity = models.ForeignKey(
        'ParentEntity', on_delete=models.CASCADE, related_name='dependent_entities'
    )

    @classmethod
    def get_status_field(cls):
        return 'parent_entity__status_id'

    class Meta:
        verbose_name = _('Dependent entity')
        verbose_name_plural = _('Dependent entities')


@bazis_triggers.register(
    FieldsTransferTrigger(
        related_field='parent_entity',
        fields={
            'author_parent': FieldTransferSchema(
                source='author',
            ),
        },
    )
)
class ExtendedEntity(
    StatusyChildMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, ExtendedEntityBase
):
    author_parent = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    parent_entity = models.OneToOneField(
        'ParentEntity', on_delete=models.CASCADE, related_name='extended_entity'
    )

    @classmethod
    def get_status_field(cls):
        return 'parent_entity__status_id'

    class Meta:
        verbose_name = _('Extended entity')
        verbose_name_plural = _('Extended entities')


class ParentEntity(StatusyMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, ParentEntityBase):
    child_entities = models.ManyToManyField(
        ChildEntity,
        related_name='parent_entities',
        blank=True,
    )

    class Meta:
        verbose_name = _('Parent entity')
        verbose_name_plural = _('Parent entities')

    @transit_validator('Must active validator')
    def validator_must_active(self, transit: TransitBase, user, payload: ParentEntityValidatedSchema):
        if payload.must_active is True and self.is_active is not True:
            raise TransitError(_('This entity must be active'))
        elif payload.must_active is False and self.is_active is not False:
            raise TransitError(_('This entity must not be active'))

    @transit_before('Datetime approved set')
    def before_dt_approved(
        self, statusy_transit: 'StatusyTransit', payload: ParentEntityBeforeSchema
    ):
        self.dt_approved = payload.dt_approved
        self.save()

    @transit_after('Datetime approved and is_active set')
    def after_child_entities(self, statusy_transit: 'StatusyTransit', payload):
        self.child_entities.all().update(
            child_dt_approved=self.dt_approved, child_is_active=self.is_active
        )
