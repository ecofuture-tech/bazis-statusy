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

from contextvars import ContextVar

from django import forms
from django.apps import apps
from django.contrib import admin
from django.forms.models import BaseInlineFormSet

from translated_fields import TranslatedFieldAdmin, to_attribute

from bazis.core.admin_abstract import AutocompleteMixin
from bazis.core.utils.sets_order import OrderedSet

from . import (
    TRANSIT_AFTER_STORE,
    TRANSIT_BEFORE_STORE,
    TRANSIT_LINK_STORE,
    TRANSIT_VALIDATORS_STORE,
)


statusy_content_type_id = ContextVar('statusy_content_type_id')


class StatusAdminBase(TranslatedFieldAdmin, admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('id', 'name')


class TransitAdminBase(TranslatedFieldAdmin, admin.ModelAdmin):
    pass


def set_choice_field(form, field_name, widget, storage):
    field_old = form.fields[field_name]
    form.fields[field_name] = widget(
        label=field_old.label,
        required=field_old.required,
        initial=field_old.initial,
        help_text=field_old.help_text,
        choices=storage.items(),
    )


def get_labels_from_store(store: dict) -> dict:
    data = {}

    # find the current model
    sct = apps.get_model('statusy.StatusyContentType').objects.get_for_id(statusy_content_type_id.get()).model_class()
    for cl in sct.mro():
        data.update(store[cl.__name__])

    return data


class TransitInlineFormSet(BaseInlineFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)

        form.fields['id'] = forms.CharField(
            required=False,
            initial='',
        )

        # create fields with sets of values from the storages of transition attribute values in the model
        set_choice_field(
            form,
            'source_link',
            forms.ChoiceField,
            {**{None: '-'}, **get_labels_from_store(TRANSIT_LINK_STORE)},
        )
        set_choice_field(
            form,
            'validators',
            forms.MultipleChoiceField,
            get_labels_from_store(TRANSIT_VALIDATORS_STORE),
        )
        set_choice_field(
            form,
            'actions_before',
            forms.MultipleChoiceField,
            get_labels_from_store(TRANSIT_BEFORE_STORE),
        )
        set_choice_field(
            form,
            'actions_after',
            forms.MultipleChoiceField,
            get_labels_from_store(TRANSIT_AFTER_STORE),
        )


class TransitInlineBase(admin.TabularInline):
    extra = 0
    formset = TransitInlineFormSet

    def get_autocomplete_fields(self, request):
        return ('status_src', 'status_dst')

    def get_fields(self, request, obj=None):
        return (
            'id',
            'name',
            'model',
            'status_src',
            'status_dst',
            'source_link',
            'validators',
            'actions_before',
            'actions_after',
            'is_schema_validate',
            'hint',
            'hint_title',
            'hint_action',
        )


class StatusyContentTypeAdminBase(admin.ModelAdmin):
    exclude = ('app_label', 'model')
    search_fields = ('app_label', 'model')

    def change_view(self, request, object_id, form_url='', extra_context=None):
        statusy_content_type_id.set(object_id)
        return self.changeform_view(request, object_id, form_url, extra_context)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


class TransitRelationInlineBase(admin.TabularInline):
    extra = 0
    fk_name = 'transit_parent'


class StatusyAdminMixin:
    def get_readonly_fields(self, request, obj=None):
        return tuple(
            OrderedSet(
                super().get_readonly_fields(request, obj)
                + (
                    'status',
                    'status_dt',
                    'status_author',
                )
            )
        )

    def get_list_display(self, request):
        return tuple(OrderedSet(super().get_list_display(request) + ('status_id',)))

    def get_search_fields(self, request):
        return tuple(
            OrderedSet(
                super().get_search_fields(request)
                + (
                    'status__id',
                    f'status__{to_attribute("name")}',
                )
            )
        )

    def get_inlines(self, request, obj):
        inlines = list(super().get_inlines(request, obj))

        if obj:
            statusy_transits_model = (
                obj.get_fields_info().reverse_relations['statusy_transits'].related_model
            )

            inlines.append(
                type(
                    f'{statusy_transits_model._meta.object_name}Inline',
                    (admin.TabularInline, AutocompleteMixin),
                    {
                        'model': statusy_transits_model,
                        'readonly_fields': (
                            'transit',
                            'status',
                            'dt',
                            'author',
                        ),
                        'exclude': ('extra',),
                        'extra': 0,
                        'can_delete': False,
                        'max_num': 0,
                        "autocomplete_fields": ("files",),
                    },
                )
            )

        return inlines
