from django.apps import apps

from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase, StatusySimpleRouteSetBase
from bazis.core.schemas import SchemaFields


class ChildEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('entity.ChildEntity')

    fields = {
        None: SchemaFields(
            include={
                'parent_entities': None,
            },
        ),
    }


class DependentEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('entity.DependentEntity')


class ExtendedEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('entity.ExtendedEntity')


class ParentEntityRouteSet(StatusyRouteSetBase):
    model = apps.get_model('entity.ParentEntity')

    # add fields (extended_entity, dependent_entities) to schema
    fields = {
        None: SchemaFields(
            include={'extended_entity': None, 'dependent_entities': None},
        ),
    }
