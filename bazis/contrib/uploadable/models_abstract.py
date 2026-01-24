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

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from bazis.core.models_abstract import JsonApiMixin
from bazis.core.utils.imp import import_class
from bazis.core.utils.orm import get_file_path


if settings.BAZIS_STORAGE_FILE_UPLOAD:
    FileStorage = import_class(settings.BAZIS_STORAGE_FILE_UPLOAD)
else:
    FileStorage = FileSystemStorage


class FileUploadAbstract(JsonApiMixin):
    file = models.FileField(_('File'), upload_to=get_file_path, max_length=255)
    name = models.CharField(_('Name'), max_length=255, blank=True, null=True)
    extension = models.CharField(_('Extension'), max_length=50, blank=True, null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta.get_field('file').storage = FileStorage()

    @cached_property
    def size(self) -> int | None:
        try:
            return self.file.size
        except FileNotFoundError:
            return 0

    def __str__(self):
        return self.file.name

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = os.path.basename(self.file.name)
        _, self.extension = (os.path.splitext(self.name) + ('',))[:2]
        self.extension = self.extension[1:]
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = _('File')
        verbose_name_plural = _('Uploadable files')
        abstract = True
