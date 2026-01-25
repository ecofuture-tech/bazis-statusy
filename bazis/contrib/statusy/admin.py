from django.contrib import admin

from . import models
from .admin_abstract import (
    StatusAdminBase,
    StatusyContentTypeAdminBase,
    TransitAdminBase,
    TransitInlineBase,
    TransitRelationInlineBase,
)


@admin.register(models.Status)
class StatusAdmin(StatusAdminBase):
    pass


class TransitInline(TransitInlineBase):
    model = models.Transit


@admin.register(models.StatusyContentType)
class StatusyContentTypeAdmin(StatusyContentTypeAdminBase):
    inlines = [TransitInline]


class TransitRelationInline(TransitRelationInlineBase):
    model = models.TransitRelation


@admin.register(models.Transit)
class TransitAdmin(TransitAdminBase):
    inlines = [TransitRelationInline]
