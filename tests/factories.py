from bazis_test_utils import factories_abstract
from entity.models import ChildEntity, DependentEntity, ExtendedEntity, ParentEntity


class ChildEntityFactory(factories_abstract.ChildEntityFactoryAbstract):
    class Meta:
        model = ChildEntity


class DependentEntityFactory(factories_abstract.DependentEntityFactoryAbstract):
    class Meta:
        model = DependentEntity


class ExtendedEntityFactory(factories_abstract.ExtendedEntityFactoryAbstract):
    class Meta:
        model = ExtendedEntity


class ParentEntityFactory(factories_abstract.ParentEntityFactoryAbstract):
    class Meta:
        model = ParentEntity
