
from django.contrib.contenttypes.models import ContentType

from .models_abstract import (
    StatusBase,
    StatusyContentTypeMixin,
    TransitBase,
    TransitRelationBase,
)


class Status(StatusBase):
    pass


class TransitRelation(TransitRelationBase):
    pass


class Transit(TransitBase):
    pass


class StatusyContentType(StatusyContentTypeMixin, ContentType):
    class Meta:
        proxy = True
