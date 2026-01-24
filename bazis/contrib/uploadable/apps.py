from django.utils.translation import gettext_lazy as _

from bazis.core.apps import BaseConfig


class UploadableConfig(BaseConfig):
    name = 'bazis.contrib.uploadable'
    verbose_name = _('Uploadable files')
