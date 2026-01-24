from django.utils.translation import gettext_lazy as _

from bazis.core.routing import BazisRouter

from .routes import FileUploadRouteSet


router = BazisRouter(tags=[_('Uploadable files')])
router.register(FileUploadRouteSet.as_router())
