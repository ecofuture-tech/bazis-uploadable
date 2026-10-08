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

from django.core.files.storage import FileSystemStorage

import pytest

from bazis.contrib.uploadable.storages import (
    S3SafeServingMixin,
    served_content_type,
    serving_storage_class,
)


class S3Storage:
    """
    Stands for `storages.backends.s3.S3Storage` of django-storages: the parameters of the
    object written on upload (`AWS_S3_OBJECT_PARAMETERS`).
    """

    object_parameters = {'CacheControl': 'max-age=60'}

    def get_object_parameters(self, name):
        return self.object_parameters.copy()


S3Storage.__module__ = 'storages.backends.s3'


class ProjectStorage(S3Storage):
    __module__ = 'project.storages'


@pytest.mark.parametrize(
    'name, content_type',
    [
        ('files/a.png', 'image/png'),
        ('files/a.JPG', 'image/jpeg'),
        ('files/a.svg', 'image/svg+xml'),
        ('files/a.html', 'text/html'),
        ('files/a', 'application/octet-stream'),
        ('files/a.unknown-type', 'application/octet-stream'),
    ],
)
def test_served_content_type_is_the_type_of_the_name(name, content_type):
    assert served_content_type(name) == content_type


@pytest.mark.parametrize(
    'name, content_type, disposition',
    [
        ('files/a.png', 'image/png', None),
        ('files/a.gif', 'image/gif', None),
        # scripts of an SVG image or an HTML page run when it is opened from the media host
        ('files/a.svg', 'image/svg+xml', 'attachment'),
        ('files/a.html', 'text/html', 'attachment'),
        ('files/a.pdf', 'application/pdf', 'attachment'),
        ('files/a', 'application/octet-stream', 'attachment'),
    ],
)
def test_s3_objects_of_active_content_are_downloads(name, content_type, disposition):
    storage = serving_storage_class(ProjectStorage)()

    params = storage.get_object_parameters(name)

    assert params['ContentType'] == content_type
    assert params.get('ContentDisposition') == disposition
    assert params['CacheControl'] == 'max-age=60'
    # the parameters of the storage are not changed
    assert ProjectStorage.object_parameters == {'CacheControl': 'max-age=60'}


def test_only_s3_storages_get_the_safe_serving():
    storage_class = serving_storage_class(ProjectStorage)
    assert issubclass(storage_class, S3SafeServingMixin)
    assert issubclass(storage_class, ProjectStorage)
    assert storage_class.__name__ == 'ProjectStorage'
    assert serving_storage_class(storage_class) is storage_class
    assert serving_storage_class(FileSystemStorage) is FileSystemStorage
