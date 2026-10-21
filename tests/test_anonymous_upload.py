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
Anonymous uploads (`BAZIS_FILE_UPLOAD_ANONYMOUS`): a guest uploads an image of the allowed
types with a size limit and a rate limit per IP address, reads back no URL and no file, and
a public action attaches it with `FileUpload.objects.anonymous(ids)`;
`uploadable_clean_anonymous` deletes the expired ones nothing references.
"""

from datetime import timedelta
from functools import partial

from django.apps import apps
from django.core.checks import run_checks
from django.core.management import call_command
from django.utils import timezone

from pydantic import TypeAdapter, ValidationError

import pytest
from bazis_test_utils.utils import get_api_client, parallel

from bazis.contrib.uploadable.conf import Settings
from bazis.contrib.uploadable.schemas import UploadedFileId

from .test_uploadable import FILES, client_of, make_user, upload


PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 30
JPEG = b'\xff\xd8\xff\xe0' + b'\0' * 30
WEBP = b'RIFF\0\0\0\0WEBPVP8 ' + b'\0' * 20


@pytest.fixture
def anonymous(settings, media):
    settings.BAZIS_FILE_UPLOAD_ANONYMOUS = True
    settings.BAZIS_FILE_UPLOAD_MAX_SIZE = 1024
    return settings


def files():
    return apps.get_model('uploadable.FileUpload').objects


def guest_upload(sample_app, filename='photo.png', content=PNG, content_type='image/png', **data):
    return client_of(sample_app).post(
        FILES, data=data, files={'file': (filename, content, content_type)}
    )


@pytest.mark.django_db(transaction=True)
def test_a_guest_uploads_an_image_and_reads_back_no_url(sample_app, anonymous):
    response = guest_upload(sample_app, name='Front door.jpeg')

    assert response.status_code == 201, response.text
    data = response.json()['data']
    assert (data['type'], data['relationships']) == ('uploadable.file_upload', {})
    # no `file` (its URL); the name keeps the extension of the type of the content
    assert data['attributes'] == {'name': 'Front door.png', 'extension': 'png', 'size': len(PNG)}
    item = files().get(pk=data['id'])
    assert item.author is None
    assert item.uploaded_anonymously is not None
    assert item.file.name.endswith('.png')
    assert item.file.read() == PNG


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('content', [JPEG, WEBP])
def test_a_guest_uploads_the_allowed_types(sample_app, anonymous, content):
    response = guest_upload(sample_app, 'photo', content, 'application/octet-stream')

    assert response.status_code == 201, response.text
    extension = response.json()['data']['attributes']['extension']
    assert extension == ('jpg' if content == JPEG else 'webp')


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    'filename,content,content_type',
    [
        ('notes.txt', b'The brief.', 'text/plain'),
        # the declared type and the name are not the type of the content
        ('photo.png', b'<html><script>alert(1)</script></html>', 'image/png'),
        ('photo.svg', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'image/png'),
        ('empty.png', b'', 'image/png'),
    ],
)
def test_a_guest_does_not_upload_another_type(
    sample_app, anonymous, filename, content, content_type
):
    response = guest_upload(sample_app, filename, content, content_type)

    assert response.status_code == 422, response.text
    error = response.json()['errors'][0]
    assert error['code'] == 'ERR_FILE_TYPE'
    assert error['source']['pointer'] == '/file'
    assert not files().exists()


@pytest.mark.django_db(transaction=True)
def test_the_allowed_types_are_configured(sample_app, anonymous):
    anonymous.BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES = ['image/png']

    assert guest_upload(sample_app, 'photo.jpg', JPEG, 'image/jpeg').status_code == 422
    assert guest_upload(sample_app).status_code == 201


def test_the_settings_refuse_an_unknown_type_and_rate():
    with pytest.raises(ValidationError, match='image/svg'):
        Settings(BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES=['image/png', 'image/svg+xml'])
    with pytest.raises(ValidationError):
        Settings(BAZIS_FILE_UPLOAD_ANONYMOUS_RATE='')
    with pytest.raises(ValidationError):
        Settings(BAZIS_FILE_UPLOAD_ANONYMOUS_TTL=0)


@pytest.mark.django_db(transaction=True)
def test_a_guest_does_not_upload_a_larger_file(sample_app, anonymous):
    anonymous.BAZIS_FILE_UPLOAD_MAX_SIZE = len(PNG) - 1

    response = guest_upload(sample_app)

    assert response.status_code == 413, response.text
    assert response.json()['errors'][0]['code'] == 'ERR_FILE_TOO_LARGE'
    assert not files().exists()


@pytest.mark.django_db(transaction=True)
def test_anonymous_uploads_need_a_size_limit(sample_app, anonymous):
    anonymous.BAZIS_FILE_UPLOAD_MAX_SIZE = 0

    assert [it.id for it in run_checks() if it.id.startswith('uploadable.')] == ['uploadable.E002']
    # without a limit nobody uploads anonymously, even if the checks were not run
    assert guest_upload(sample_app).status_code == 401
    assert not files().exists()

    anonymous.BAZIS_FILE_UPLOAD_MAX_SIZE = 1024
    assert [it.id for it in run_checks() if it.id.startswith('uploadable.')] == []


@pytest.mark.django_db(transaction=True)
def test_anonymous_uploads_are_off_by_default(sample_app, media, settings):
    assert settings.BAZIS_FILE_UPLOAD_ANONYMOUS is False
    settings.BAZIS_FILE_UPLOAD_MAX_SIZE = 1024

    assert guest_upload(sample_app).status_code == 401
    assert not files().exists()


@pytest.mark.django_db(transaction=True)
def test_the_anonymous_uploads_are_throttled_by_ip(sample_app, anonymous):
    anonymous.BAZIS_FILE_UPLOAD_ANONYMOUS_RATE = '2/hour'

    assert [guest_upload(sample_app).status_code for _ in range(3)] == [201, 201, 429]
    response = guest_upload(sample_app)
    assert response.json()['errors'][0]['code'] == 'ERR_THROTTLED'
    assert int(response.headers['Retry-After']) > 0
    # a logged-in user from the same address is not limited
    client = client_of(sample_app, make_user('owner'))
    assert [upload(client).status_code for _ in range(3)] == [201, 201, 201]
    assert files().filter(author__isnull=True).count() == 2


@pytest.mark.django_db(transaction=True)
def test_a_guest_reads_no_file(sample_app, anonymous):
    item = guest_upload(sample_app).json()['data']['id']
    guest = client_of(sample_app)

    assert guest.get(FILES).status_code == 401
    assert guest.get(f'{FILES}_id/').status_code == 401
    assert guest.get(f'{FILES}{item}/').status_code == 401
    assert guest.get(f'{FILES}{item}/download/').status_code == 401
    # nor does a user: an anonymous upload is nobody's until an object references it
    user = client_of(sample_app, make_user('owner'))
    assert user.get(FILES).json()['data'] == []
    assert user.get(f'{FILES}{item}/').status_code == 404
    assert user.get(f'{FILES}{item}/download/').status_code == 404


@pytest.mark.django_db(transaction=True)
def test_a_user_uploads_as_before_when_anonymous_uploads_are_on(sample_app, anonymous):
    owner = make_user('owner')

    response = upload(client_of(sample_app, owner), 'notes.txt')

    assert response.status_code == 201, response.text
    attributes = response.json()['data']['attributes']
    assert attributes['name'] == 'notes.txt'
    assert attributes['file']
    item = files().get()
    assert (item.author, item.uploaded_anonymously) == (owner, None)
    # an invalid token is not an anonymous user
    response = get_api_client(sample_app, 'invalid').post(
        FILES, files={'file': ('photo.png', PNG, 'image/png')}
    )
    assert response.status_code == 401
    assert files().count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_uploads_of_users_and_guests_do_not_mix(sample_app, anonymous):
    """
    The author is the user of each request: a guest after a user, and many at once.
    """
    owner = make_user('owner')
    client = client_of(sample_app, owner)
    assert upload(client).status_code == 201
    assert guest_upload(sample_app).status_code == 201

    responses = parallel(
        [partial(guest_upload, sample_app, f'guest-{it}.png') for it in range(8)]
        + [partial(upload, client, f'user-{it}.txt') for it in range(8)]
    )

    assert [it.status_code for it in responses] == [201] * 16
    for item in files().all():
        assert (item.author is None) == item.name.startswith(('guest-', 'photo')), item.name
        assert (item.uploaded_anonymously is None) == (item.author is not None)


@pytest.mark.django_db(transaction=True)
def test_anonymous_takes_only_the_fresh_anonymous_uploads(sample_app, anonymous):
    owner = make_user('owner')
    fresh, expired = (guest_upload(sample_app).json()['data']['id'] for _ in range(2))
    files().filter(pk=expired).update(uploaded_anonymously=timezone.now() - timedelta(hours=25))
    own = upload(client_of(sample_app, owner)).json()['data']['id']
    generated = files().create_for(None, 'report.txt', 'The report.').pk

    ids = [fresh, expired, own, generated, 0]
    assert [str(it.pk) for it in files().anonymous(ids)] == [str(fresh)]
    assert list(files().anonymous([])) == []

    anonymous.BAZIS_FILE_UPLOAD_ANONYMOUS_TTL = 26
    assert {str(it.pk) for it in files().anonymous(ids)} == {str(fresh), str(expired)}


@pytest.mark.django_db(transaction=True)
def test_the_clean_deletes_the_expired_anonymous_uploads_nothing_references(sample_app, anonymous):
    Note, Board = apps.get_model('notes.Note'), apps.get_model('notes.Board')  # noqa: N806
    owner = make_user('owner')
    expired, noted, boarded, fresh = (
        files().get(pk=guest_upload(sample_app).json()['data']['id']) for _ in range(4)
    )
    files().exclude(pk=fresh.pk).update(uploaded_anonymously=timezone.now() - timedelta(hours=25))
    # the public action attached two of them (a foreign key and a many-to-many field)
    Note.objects.create(title='Leak', attachment=noted)
    Board.objects.create(title='Leaks').files.add(boarded)
    own = files().get(pk=upload(client_of(sample_app, owner)).json()['data']['id'])
    generated = files().create_for(None, 'report.txt', 'The report.')
    storage = expired.file.storage
    assert storage.exists(expired.file.name)

    call_command('uploadable_clean_anonymous')

    kept = {noted.pk, boarded.pk, fresh.pk, own.pk, generated.pk}
    assert set(files().values_list('pk', flat=True)) == kept
    assert not storage.exists(expired.file.name)
    for item in files().all():
        assert storage.exists(item.file.name)


def test_uploaded_file_id_marks_the_files():
    marker = {'x-relation': 'uploadable.file_upload'}

    assert TypeAdapter(UploadedFileId).json_schema() == {'type': 'integer', **marker}
    assert TypeAdapter(list[UploadedFileId]).json_schema()['items'] == {
        'type': 'integer',
        **marker,
    }
    assert TypeAdapter(list[UploadedFileId]).validate_python(['12', 13]) == [12, 13]
