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

from django.apps import apps
from django.contrib.auth import get_user_model

import pytest
from bazis_test_utils.utils import get_api_client

from .factories import FileUploadFactory


FILES = '/api/v1/uploadable/file_upload/'
NOTES = '/api/v1/notes/note/'


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def make_user(name):
    return get_user_model().objects.create_user(name, password=f'{name}-password-1')


def client_of(sample_app, user=None):
    return get_api_client(sample_app, user.jwt_build() if user else None)


def upload(client, filename='brief.txt', content=b'The brief.', **data):
    return client.post(FILES, data=data, files={'file': (filename, content, 'text/plain')})


def ids(response):
    return [str(it['id']) for it in response.json()['data']]


@pytest.mark.django_db(transaction=True)
def test_upload_is_owned_by_its_author(sample_app, media):
    owner = make_user('owner')

    response = upload(client_of(sample_app, owner), name='Test_name.txt')

    assert response.status_code == 201, response.text
    data = response.json()['data']
    assert data['type'] == 'uploadable.file_upload'
    assert data['attributes']['extension'] == 'txt'
    assert data['attributes']['size'] == 10
    # the author is not shown: an attachment read through `include` hides who uploaded it
    assert 'author' not in data.get('relationships', {})
    item = apps.get_model('uploadable.FileUpload').objects.get(pk=data['id'])
    assert item.author == owner
    assert item.extension == 'txt'


@pytest.mark.django_db(transaction=True)
def test_a_user_sees_only_his_files(sample_app, media):
    owner, stranger = make_user('owner'), make_user('stranger')
    own = str(upload(client_of(sample_app, owner)).json()['data']['id'])
    other = str(upload(client_of(sample_app, stranger)).json()['data']['id'])
    # a file without an author (uploaded elsewhere, before 2.5) is nobody's
    FileUploadFactory.create()

    client = client_of(sample_app, owner)
    assert ids(client.get(FILES)) == [own]
    assert client.get(f'{FILES}_id/').json() == [own]
    assert client.get(f'{FILES}{own}/').status_code == 200
    assert client.get(f'{FILES}{other}/').status_code == 404
    assert ids(client_of(sample_app, stranger).get(FILES)) == [other]


@pytest.mark.django_db(transaction=True)
def test_files_are_not_changed_or_deleted(sample_app, media):
    owner, stranger = make_user('owner'), make_user('stranger')
    item = upload(client_of(sample_app, owner)).json()['data']['id']
    body = {'data': {'id': item, 'type': 'uploadable.file_upload', 'attributes': {'name': 'x.html'}}}

    for user in (owner, stranger):
        client = client_of(sample_app, user)
        assert client.patch(f'{FILES}{item}/', json_data=body).status_code == 405
        assert client.delete(f'{FILES}{item}/').status_code == 405
        response = client.patch(
            f'{FILES}{item}/relationships/author/',
            json_data={'data': {'id': str(stranger.pk), 'type': 'users.user'}},
        )
        assert response.status_code in (404, 405)

    item = apps.get_model('uploadable.FileUpload').objects.get(pk=item)
    assert (item.name, item.author) == ('brief.txt', owner)


@pytest.mark.django_db(transaction=True)
def test_anonymous_user_uploads_and_reads_nothing(sample_app, media):
    item = upload(client_of(sample_app, make_user('owner'))).json()['data']['id']

    client = client_of(sample_app)
    assert upload(client).status_code == 401
    assert client.get(FILES).status_code == 401
    assert client.get(f'{FILES}{item}/').status_code == 401
    assert apps.get_model('uploadable.FileUpload').objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_client_does_not_choose_the_id(sample_app, media):
    owner = make_user('owner')

    response = upload(client_of(sample_app, owner), id='987654')

    assert response.status_code == 201, response.text
    assert str(response.json()['data']['id']) != '987654'
    assert not apps.get_model('uploadable.FileUpload').objects.filter(pk=987654).exists()


@pytest.mark.django_db(transaction=True)
def test_referenced_file_is_read_through_the_referencing_resource(sample_app, media):
    author, reader = make_user('author'), make_user('reader')
    item = upload(client_of(sample_app, author), 'plan.txt').json()['data']['id']
    note = apps.get_model('notes.Note').objects.create(title='Plan', attachment_id=item)

    client = client_of(sample_app, reader)
    assert client.get(f'{FILES}{item}/').status_code == 404
    response = client.get(f'{NOTES}{note.pk}/', params={'include': 'attachment'})

    assert response.status_code == 200, response.text
    [included] = response.json()['included']
    assert (included['type'], included['id']) == ('uploadable.file_upload', item)
    assert included['attributes']['name'] == 'plan.txt'
    assert included['attributes']['file'].endswith('.txt')
    assert 'author' not in included.get('relationships', {})


@pytest.mark.django_db(transaction=True)
def test_uploadable_max_size(sample_app, media, settings):
    settings.BAZIS_FILE_UPLOAD_MAX_SIZE = 10
    model = apps.get_model('uploadable.FileUpload')
    client = client_of(sample_app, make_user('owner'))

    response = upload(client, 'large.txt', b'x' * 11)
    assert response.status_code == 413
    assert response.json()['errors'][0]['code'] == 'ERR_FILE_TOO_LARGE'
    assert not model.objects.exists()

    response = upload(client, 'small.txt', b'x' * 10)
    assert response.status_code == 201
    file_instance = model.objects.get()
    assert file_instance.size == 10
    assert file_instance.file.storage.location == str(media)
