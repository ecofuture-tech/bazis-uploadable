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
a public action attaches it by its token with `FileUpload.objects.anonymous(tokens)`;
`uploadable_clean_anonymous` deletes the expired ones nothing references.
"""

import subprocess
import sys
import time
from datetime import timedelta
from functools import partial
from pathlib import Path

from django.apps import apps
from django.core.checks import run_checks
from django.core.management import CommandError, call_command
from django.core.signing import TimestampSigner, b62_encode
from django.db import DatabaseError
from django.db.models.signals import pre_delete
from django.utils import timezone

from pydantic import TypeAdapter, ValidationError

import pytest
from bazis_test_utils.utils import get_api_client, parallel

from bazis.contrib.uploadable.conf import Settings
from bazis.contrib.uploadable.models_abstract import ANONYMOUS_SALT, anonymous_token
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


def pk_of(response) -> str:
    """The id of the upload of a guest: the token he reads back is signed."""
    return TimestampSigner(salt=ANONYMOUS_SALT).unsign(response.json()['data']['id'])


def raw_upload(client, filename: str, name: str | None = None):
    """A multipart upload written by hand: httpx does not send any file name."""
    parts = (
        []
        if name is None
        else [f'--B\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode()]
    )
    parts.append(
        f'--B\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        'Content-Type: image/png\r\n\r\n'.encode()
        + PNG
        + b'\r\n--B--\r\n'
    )
    headers = client.headers | {'Content-Type': 'multipart/form-data; boundary=B'}
    return client.client.post(FILES, content=b''.join(parts), headers=headers)


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
    # the id is the token of the upload, its signed id
    item = files().get(pk=pk_of(response))
    assert data['id'] == anonymous_token(item.pk) != str(item.pk)
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
    item = pk_of(guest_upload(sample_app))
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


class PastSigner(TimestampSigner):
    """Signs as 25 hours ago."""

    def timestamp(self):
        return b62_encode(int(time.time() - 25 * 3600))


@pytest.mark.django_db(transaction=True)
def test_anonymous_takes_the_fresh_uploads_of_the_tokens(sample_app, anonymous):
    owner = make_user('owner')
    fresh, expired, again = (guest_upload(sample_app).json()['data']['id'] for _ in range(3))
    expired_pk = TimestampSigner(salt=ANONYMOUS_SALT).unsign(expired)
    files().filter(pk=expired_pk).update(uploaded_anonymously=timezone.now() - timedelta(hours=25))
    fresh_pk = TimestampSigner(salt=ANONYMOUS_SALT).unsign(fresh)
    again_pk = TimestampSigner(salt=ANONYMOUS_SALT).unsign(again)
    own = upload(client_of(sample_app, owner)).json()['data']['id']
    generated = files().create_for(None, 'report.txt', 'The report.').pk

    def taken(tokens):
        return sorted(str(it.pk) for it in files().anonymous(tokens))

    assert taken([fresh]) == [fresh_pk]
    # a token is not used up: the guest who has it attaches it again
    assert taken([fresh, fresh]) == [fresh_pk]
    assert taken([fresh]) == [fresh_pk]
    assert taken([]) == []
    # never by a bare id, a forged or expired token, nor a file of a user or of the server
    assert taken([fresh_pk, int(again_pk), str(own), own]) == []
    assert taken([fresh[:-1] + ('A' if fresh[-1] != 'A' else 'B')]) == []
    assert taken([TimestampSigner(salt='another').sign(again_pk)]) == []
    assert taken([PastSigner(salt=ANONYMOUS_SALT).sign(again_pk)]) == []
    assert taken([anonymous_token(own), anonymous_token(generated)]) == []
    assert taken([expired]) == []

    anonymous.BAZIS_FILE_UPLOAD_ANONYMOUS_TTL = 26
    assert taken([fresh, expired, PastSigner(salt=ANONYMOUS_SALT).sign(again_pk)]) == sorted(
        [fresh_pk, expired_pk, again_pk]
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('field', ['name', 'file'])
def test_a_name_with_a_control_character_is_refused(sample_app, anonymous, media, field):
    owner = make_user('owner')
    for client in (client_of(sample_app), client_of(sample_app, owner)):
        if field == 'name':
            response = raw_upload(client, 'photo.png', name='photo\x00.png')
        else:
            response = raw_upload(client, 'photo\x00.png\x07')

        assert response.status_code == 422, response.text
        error = response.json()['errors'][0]
        assert (error['code'], error['source']['pointer']) == ('ERR_FILE_NAME', f'/{field}')
    assert not files().exists()
    # nothing reached the storage
    assert not any(it.is_file() for it in media.rglob('*'))
    assert raw_upload(client_of(sample_app), 'photo.png', name='Photo 1.png').status_code == 201


def expire(*items):
    files().filter(pk__in=[it.pk for it in items]).update(
        uploaded_anonymously=timezone.now() - timedelta(hours=25)
    )


@pytest.mark.django_db(transaction=True)
def test_the_clean_deletes_the_expired_anonymous_uploads_nothing_references(sample_app, anonymous):
    Note, Board = apps.get_model('notes.Note'), apps.get_model('notes.Board')  # noqa: N806
    owner = make_user('owner')
    expired, noted, boarded, unboarded, fresh = (
        files().get(pk=pk_of(guest_upload(sample_app))) for _ in range(5)
    )
    expire(expired, noted, boarded, unboarded)
    # the public action attached two of them (a foreign key and a many-to-many field); a
    # board that no longer has a file does not keep it
    Note.objects.create(title='Leak', attachment=noted)
    Board.objects.create(title='Leaks').files.add(boarded)
    board = Board.objects.create(title='Gone')
    board.files.add(unboarded)
    board.files.remove(unboarded)
    own = files().get(pk=upload(client_of(sample_app, owner)).json()['data']['id'])
    generated = files().create_for(None, 'report.txt', 'The report.')
    storage = expired.file.storage
    assert storage.exists(expired.file.name)

    call_command('uploadable_clean_anonymous')

    kept = {noted.pk, boarded.pk, fresh.pk, own.pk, generated.pk}
    assert set(files().values_list('pk', flat=True)) == kept
    assert not storage.exists(expired.file.name)
    assert not storage.exists(unboarded.file.name)
    for item in files().all():
        assert storage.exists(item.file.name)


@pytest.mark.django_db(transaction=True)
def test_the_clean_goes_on_after_a_failure(sample_app, anonymous, monkeypatch, capsys):
    """
    A row that fails to be deleted and a file that fails to be deleted from the storage are
    reported; the others are deleted and the command exits with an error.
    """
    stuck, lost, gone = (files().get(pk=pk_of(guest_upload(sample_app))) for _ in range(3))
    expire(stuck, lost, gone)
    storage_class = type(lost.file.storage)
    storage_delete = storage_class.delete

    def refuse(sender, instance, **kwargs):
        if instance.pk == stuck.pk:
            raise DatabaseError('the row is locked')

    def delete(storage, name):
        if name == lost.file.name:
            raise OSError('the storage is down')
        storage_delete(storage, name)

    monkeypatch.setattr(storage_class, 'delete', delete)
    pre_delete.connect(refuse, sender=type(stuck))
    try:
        with pytest.raises(CommandError, match='2 anonymous uploads'):
            call_command('uploadable_clean_anonymous')
    finally:
        pre_delete.disconnect(refuse, sender=type(stuck))

    errors = capsys.readouterr().err
    assert 'the row is locked' in errors and lost.file.name in errors
    assert set(files().values_list('pk', flat=True)) == {stuck.pk}
    storage = gone.file.storage
    assert not storage.exists(gone.file.name)
    # the row of the lost file is deleted, its file stays (reported)
    assert storage.exists(lost.file.name) and storage.exists(stuck.file.name)


def test_uploaded_file_id_marks_the_files():
    marker = {'type': 'string', 'x-relation': 'uploadable.file_upload'}

    assert TypeAdapter(UploadedFileId).json_schema() == marker
    assert TypeAdapter(list[UploadedFileId]).json_schema()['items'] == marker


def test_the_users_read_the_fields_of_2_7(sample_app):
    """
    `uploaded_anonymously` is in none of the schemas of the route of the files.
    """
    schemas = sample_app.openapi()['components']['schemas']
    names = [it for it in schemas if it.startswith('___uploadable__file_upload__schema_')]
    assert names
    for name in names:
        assert 'uploaded_anonymously' not in schemas[name]['properties'], name
    retrieve = [it for it in names if '_retrieve__' in it and it.endswith('__Attributes')]
    assert [set(schemas[it]['properties']) for it in retrieve] == [
        {'file', 'name', 'extension', 'size'}
    ]


@pytest.mark.parametrize(
    'environ,public',
    [
        ({'BS_BAZIS_FILE_UPLOAD_ANONYMOUS': 'true', 'BS_BAZIS_FILE_UPLOAD_MAX_SIZE': '1000'}, True),
        ({'BS_BAZIS_FILE_UPLOAD_ANONYMOUS': 'true', 'BS_BAZIS_FILE_UPLOAD_MAX_SIZE': '0'}, False),
    ],
)
def test_the_upload_is_public_with_anonymous_uploads(monkeypatch, environ, public):
    """
    `public` of the upload route (read when the routes are imported, in a process of its
    own) is `anonymous_uploads()`: on with a size limit.
    """
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    code = (
        'import django; django.setup()\n'
        'from bazis.contrib.uploadable.routes import FileUploadRouteSet, anonymous_uploads\n'
        'route = FileUploadRouteSet.endpoint_make(FileUploadRouteSet.action_create)\n'
        'print(FileUploadRouteSet.route_meta(route)["public"], anonymous_uploads())\n'
    )
    monkeypatch.setenv('DJANGO_SETTINGS_MODULE', 'sample.settings')
    result = subprocess.run(
        [sys.executable, '-c', code],
        cwd=Path(__file__).resolve().parent.parent / 'sample',
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split()[-2:] == [str(public), str(public)]
