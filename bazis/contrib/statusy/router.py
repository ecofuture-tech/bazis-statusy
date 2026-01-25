from django.utils.translation import gettext_lazy as _

from bazis.core.routing import BazisRouter

from .routes import StatusRoute, TransitRoute


router = BazisRouter(tags=[_('Status model')])
router.register(StatusRoute.as_router())
router.register(TransitRoute.as_router())
