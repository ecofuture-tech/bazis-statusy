from django.utils.translation import gettext_lazy as _

from bazis.core.utils.apps import BaseConfig


class StatusyConfig(BaseConfig):
    name = 'bazis.contrib.statusy'
    verbose_name = _('Statusy')

    def ready(self):
        super().ready()

        from .models_abstract import StatusyChildMixin

        for model in StatusyChildMixin.get_inheritors():
            model._statusy_register()

