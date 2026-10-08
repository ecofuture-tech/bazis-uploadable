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


def note_body(title, file_id=None, note_id=None):
    data = {'type': 'notes.note', 'attributes': {'title': title}}
    if note_id is not None:
        data['id'] = str(note_id)
    if file_id is not None:
        data['relationships'] = {
            'attachment': {'data': {'type': 'uploadable.file_upload', 'id': str(file_id)}}
        }
    return {'data': data}


@pytest.mark.django_db(transaction=True)
def test_included_shows_only_own_files(sample_app, media):
    """
    `included` of another route (the notes) shows only the files the user uploaded: the
    default route of the files restricts them; the relationship keeps the identifier.
    """
    alice, bob = make_user('alice'), make_user('bob')
    alice_client, bob_client = client_of(sample_app, alice), client_of(sample_app, bob)
    item = upload(alice_client, 'plan.txt').json()['data']['id']
    response = alice_client.post(NOTES, json_data=note_body('Plan', item))
    assert response.status_code == 201, response.text
    note = response.json()['data']['id']

    response = alice_client.get(f'{NOTES}{note}/', params={'include': 'attachment'})
    [included] = response.json()['included']
    assert (included['type'], included['id']) == ('uploadable.file_upload', item)
    assert included['attributes']['name'] == 'plan.txt'
    assert 'author' not in included.get('relationships', {})

    assert bob_client.get(f'{FILES}{item}/').status_code == 404
    response = bob_client.get(f'{NOTES}{note}/', params={'include': 'attachment'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['data']['relationships']['attachment']['data']['id'] == str(item)
    assert data.get('included', []) == []

    # bob changes the note of alice and keeps her attachment: a kept link is not checked
    response = bob_client.patch(f'{NOTES}{note}/', json_data=note_body('Plan 2', note_id=note))
    assert response.status_code == 200, response.text


@pytest.mark.django_db(transaction=True)
def test_a_user_does_not_attach_the_file_of_another_user(sample_app, media):
    """
    The route set of the notes has no checks of its own: the core refuses a file the
    user did not upload (create, update and the relationships endpoints).
    """
    alice, bob = make_user('alice'), make_user('bob')
    alice_file = upload(client_of(sample_app, alice), 'secret.txt').json()['data']['id']
    client = client_of(sample_app, bob)
    bob_file = upload(client, 'own.txt').json()['data']['id']
    notes = apps.get_model('notes.Note').objects

    response = client.post(NOTES, json_data=note_body('Steal', alice_file))
    assert response.status_code == 403, response.text
    error = response.json()['errors'][0]
    assert error['code'] == 'ERR_RELATION_ACCESS'
    assert error['source']['pointer'] == '/data/relationships/attachment'
    assert not notes.exists()

    response = client.post(NOTES, json_data=note_body('Own', bob_file))
    assert response.status_code == 201, response.text
    note = response.json()['data']['id']

    response = client.patch(f'{NOTES}{note}/', json_data=note_body('Steal', alice_file, note))
    assert response.status_code == 403, response.text
    response = client.patch(
        f'{NOTES}{note}/relationships/attachment/',
        json_data={'data': {'type': 'uploadable.file_upload', 'id': str(alice_file)}},
    )
    assert response.status_code == 403, response.text
    assert notes.get(pk=note).attachment_id == bob_file
    included = client.get(f'{NOTES}{note}/', params={'include': 'attachment'}).json()['included']
    assert [it['id'] for it in included] == [bob_file]


@pytest.mark.django_db(transaction=True)
def test_files_without_an_authenticated_user():
    """
    `restrict_queryset` never fails without a user: an anonymous user sees no file, a
    missing user is the authenticated user of the request, if any.
    """
    from bazis.contrib.uploadable.routes import FileUploadRouteSet
    from bazis.contrib.users import get_anonymous_user_model
    from bazis.contrib.users.models_abstract import UserMixin
    from bazis.core.schemas import CrudAccessAction

    owner = make_user('owner')
    item = FileUploadFactory.create(author=owner)
    files = apps.get_model('uploadable.FileUpload').objects.all()

    def visible(**kwargs):
        return list(FileUploadRouteSet.restrict_queryset(files, CrudAccessAction.VIEW, **kwargs))

    assert visible() == []
    assert visible(user=get_anonymous_user_model()()) == []
    assert visible(user=owner) == [item]
    token = UserMixin.CTX_USER_REQUEST.set(owner)
    try:
        assert visible() == [item]
    finally:
        UserMixin.CTX_USER_REQUEST.reset(token)


@pytest.mark.django_db(transaction=True)
def test_a_subclass_widens_the_visible_files(sample_app, media, monkeypatch):
    """
    The pattern of AGENTS.md: the default route of the files shows also the files of the
    notes (every user reads every note), so the attachments of shared notes are linked
    and included for everybody.
    """
    from django.db.models import Q

    from bazis.contrib.uploadable.routes import FileUploadRouteSet
    from bazis.contrib.users.models_abstract import UserMixin
    from bazis.core.schemas import CrudAccessAction

    FileUpload = apps.get_model('uploadable.FileUpload')  # noqa: N806
    Note = apps.get_model('notes.Note')  # noqa: N806
    # a route class becomes the default route of its model: restore it
    monkeypatch.setattr(FileUpload, '_default_route', FileUpload.get_default_route())

    class SharedFileRouteSet(FileUploadRouteSet):
        default_route = True

        @classmethod
        def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
            user = user or UserMixin.CTX_USER_REQUEST.get()
            own = super().restrict_queryset(qs, access_action, user=user, **kwargs)
            if user is None or user.is_anonymous:
                return own
            return qs.filter(Q(pk__in=own.values('pk')) | Q(pk__in=Note.objects.values('attachment')))

    assert FileUpload.get_default_route() is SharedFileRouteSet
    # registered instead of the bundled router, it serves the same URLs
    assert SharedFileRouteSet.get_url_prefix() == FileUploadRouteSet.get_url_prefix()
    assert SharedFileRouteSet.get_url_prefix() == '/uploadable/file_upload'

    alice, bob = make_user('alice'), make_user('bob')
    alice_client, bob_client = client_of(sample_app, alice), client_of(sample_app, bob)
    attached = upload(alice_client, 'plan.txt').json()['data']['id']
    private = upload(alice_client, 'secret.txt').json()['data']['id']
    note = alice_client.post(NOTES, json_data=note_body('Plan', attached)).json()['data']['id']

    response = bob_client.get(f'{NOTES}{note}/', params={'include': 'attachment'})
    assert [it['id'] for it in response.json()['included']] == [attached]
    assert bob_client.post(NOTES, json_data=note_body('Copy', attached)).status_code == 201
    response = bob_client.post(NOTES, json_data=note_body('Steal', private))
    assert response.status_code == 403
    assert response.json()['errors'][0]['code'] == 'ERR_RELATION_ACCESS'

    # called without a user, the own files and the shared ones are of the request user
    own = upload(bob_client, 'own.txt').json()['data']['id']
    files = FileUpload.objects.all()
    token = UserMixin.CTX_USER_REQUEST.set(bob)
    try:
        visible = SharedFileRouteSet.restrict_queryset(files, CrudAccessAction.VIEW)
        assert {str(it.pk) for it in visible} == {str(attached), str(own)}
    finally:
        UserMixin.CTX_USER_REQUEST.reset(token)


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
