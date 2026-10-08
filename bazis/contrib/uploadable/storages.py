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

"""
How the uploaded files are served. An uploaded file is whatever a client sent: an HTML page
or an SVG image runs its scripts when it is opened from the media host. Only raster images
are shown inline; every other file is a download (`Content-Disposition: attachment`), and
the type of a file is the one of its name, not the one the client declared.

The headers are set by whoever serves the files: the web server of `MEDIA_ROOT` for the
file system storage (see AGENTS.md), the object metadata written on upload for an S3
storage of django-storages (`S3SafeServingMixin`, added by `serving_storage_class`).
"""

import mimetypes


#: the types that a browser shows inline without running code of the file
INLINE_CONTENT_TYPES = frozenset(
    {'image/avif', 'image/bmp', 'image/gif', 'image/jpeg', 'image/png', 'image/webp'}
)


def served_content_type(name: str) -> str:
    """
    The type a stored file is served with: the type of its name, else
    `application/octet-stream`.
    """
    return mimetypes.guess_type(name)[0] or 'application/octet-stream'


class S3SafeServingMixin:
    """
    A mixin of the S3 storage of django-storages (`storages.backends.s3.S3Storage`): the
    object of an uploaded file is written with the type of its name (S3 otherwise stores the
    type the client declared) and, unless it is a raster image, with
    `Content-Disposition: attachment`.
    """

    def get_object_parameters(self, name):
        params = super().get_object_parameters(name)
        params['ContentType'] = served_content_type(name)
        if params['ContentType'] not in INLINE_CONTENT_TYPES:
            params['ContentDisposition'] = 'attachment'
        return params


def serving_storage_class(storage_class: type) -> type:
    """
    The storage class of the uploaded files for the class of `BAZIS_STORAGE_FILE_UPLOAD`: an
    S3 storage of django-storages (or a subclass of it) gets `S3SafeServingMixin`, any other
    class is returned as is.
    """
    if issubclass(storage_class, S3SafeServingMixin) or not any(
        base.__module__.startswith('storages.backends.s3') for base in storage_class.__mro__
    ):
        return storage_class
    return type(storage_class.__name__, (S3SafeServingMixin, storage_class), {})
