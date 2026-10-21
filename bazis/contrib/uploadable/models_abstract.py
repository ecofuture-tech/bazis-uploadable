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
from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from bazis.contrib.author.models_abstract import AuthorMixin
from bazis.core.utils.imp import import_class
from bazis.core.utils.orm import get_file_path

from .storages import serving_storage_class


if settings.BAZIS_STORAGE_FILE_UPLOAD:
    FileStorage = serving_storage_class(import_class(settings.BAZIS_STORAGE_FILE_UPLOAD))
else:
    FileStorage = FileSystemStorage


def get_file_upload_storage():
    """
    Returns the storage of the uploaded files: the class from BAZIS_STORAGE_FILE_UPLOAD
    (an S3 storage of django-storages serves the files safely, see `storages`), or the
    file system storage in MEDIA_ROOT.
    """
    return FileStorage()


def anonymous_expiry():
    """
    The time before which an anonymous upload is expired: `BAZIS_FILE_UPLOAD_ANONYMOUS_TTL`
    hours ago.
    """
    return timezone.now() - timedelta(hours=settings.BAZIS_FILE_UPLOAD_ANONYMOUS_TTL)


class FileUploadManager(models.Manager):
    """
    The manager of the uploaded files, with `create_for` for the files the server writes and
    `anonymous` for the files anonymous users uploaded.
    """

    def anonymous(self, ids: Iterable):
        """
        The anonymous uploads among `ids` that a public action may attach to the object it
        creates: uploaded by an anonymous user (no author) at most
        `BAZIS_FILE_UPLOAD_ANONYMOUS_TTL` hours ago. The files of users and the expired ones
        are left out.
        """
        return self.filter(
            pk__in=ids, author__isnull=True, uploaded_anonymously__gte=anonymous_expiry()
        )

    def anonymous_expired(self):
        """
        The expired anonymous uploads that no object references (by any foreign key,
        one-to-one or many-to-many field to the model): what `uploadable_clean_anonymous`
        deletes.
        """
        qs = self.filter(author__isnull=True, uploaded_anonymously__lt=anonymous_expiry())
        for rel in self.model._meta.get_fields(include_hidden=True):
            if rel.auto_created and not rel.concrete:
                name = rel.field.name
                qs = qs.exclude(
                    pk__in=rel.related_model._base_manager.filter(
                        **{f'{name}__isnull': False}
                    ).values(name)
                )
        return qs

    def create_for(self, author, name: str, content: bytes | str | File):
        """
        Stores a file the server generated (a PDF, a report) as an uploaded file of `author`
        and returns it: `name` is its name (and the extension of the stored file), `content`
        its bytes, a text (UTF-8) or a Django `File`. `author` is the owner who sees it and
        links it to objects; None keeps it without an author outside a request (inside one
        bazis-author makes the user of the request its author). Whoever else should read
        it sees it through the objects that reference it (`files_visible`). The size limit
        of the uploads does not apply.
        """
        if isinstance(content, str):
            content = content.encode()
        if not isinstance(content, File):
            content = ContentFile(content)
        item = self.model(author=author, name=name)
        item.file.save(name, content, save=False)
        item.save()
        return item


class FileUploadAbstract(AuthorMixin):
    """
    An uploaded file. Its `author` (bazis-author) is the user who uploaded it: the route set
    `FileUploadRouteSet` shows a user his files and the files of the objects he sees
    through a route set that declares them in `files_visible`.
    """

    objects = FileUploadManager()

    file = models.FileField(
        _('File'), upload_to=get_file_path, max_length=255, storage=get_file_upload_storage
    )
    name = models.CharField(_('Name'), max_length=255, blank=True, null=True)
    extension = models.CharField(_('Extension'), max_length=50, blank=True, null=True)
    #: when an anonymous user uploaded it (None for the files of users and of the server)
    uploaded_anonymously = models.DateTimeField(
        _('Uploaded anonymously'), blank=True, null=True, editable=False
    )

    @cached_property
    def size(self) -> int | None:
        """
        The size of the stored file, 0 if the file is missing from the storage.
        """
        try:
            return self.file.size
        except OSError:
            return 0

    def __str__(self):
        return self.file.name

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = os.path.basename(self.file.name)
        self.extension = os.path.splitext(self.name)[1][1:]
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = _('File')
        verbose_name_plural = _('Uploadable files')
        abstract = True
