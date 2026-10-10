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
`files_visible` of a route set: the files its objects reference are visible to whoever sees
the objects (the sample: `notes.Memo` with `attachment`, `notes.Board` with `files`); a user
links only his own files (422 for a visible file of another user); the content is
downloaded through the route of the files, with its access check.
"""

from types import SimpleNamespace

from django.apps import apps
from django.db.models import Q

import pytest

from bazis.contrib.uploadable.checks import check_files_visible, files_visible_errors
from bazis.contrib.uploadable.models import FileUpload
from bazis.contrib.uploadable.routes import (
    FileUploadRouteSet,
    files_visible_cache_clear,
    files_visible_routes,
)
from bazis.core.schemas import CrudAccessAction

from .test_uploadable import FILES, NOTES, client_of, ids, make_user, note_body, upload


MEMOS = '/api/v1/notes/memo/'
BOARDS = '/api/v1/notes/board/'


def Memo():  # noqa: N802
    return apps.get_model('notes.Memo')


def Board():  # noqa: N802
    return apps.get_model('notes.Board')


def upload_id(client, filename='plan.txt', content=b'The plan.'):
    response = upload(client, filename, content)
    assert response.status_code == 201, response.text
    return str(response.json()['data']['id'])


def relationship(type_, *pks, many=False):
    data = [{'type': type_, 'id': str(pk)} for pk in pks]
    return {'data': data if many else (data[0] if data else None)}


def assert_not_linkable(response, pointer):
    assert response.status_code == 422, response.text
    error = response.json()['errors'][0]
    assert error['code'] == 'ERR_RELATION_LINK'
    assert error['source'] == {'pointer': pointer}


@pytest.mark.django_db(transaction=True)
def test_a_file_is_visible_with_the_object_that_references_it(sample_app, media):
    alice, bob, carol = make_user('alice'), make_user('bob'), make_user('carol')
    alice_client = client_of(sample_app, alice)
    attachment = upload_id(alice_client, 'plan.txt', b'The plan.')
    cover = upload_id(alice_client, 'cover.txt')
    memo = Memo().objects.create(title='Plan', owner=alice, attachment_id=attachment, cover_id=cover)
    memo.readers.add(bob)

    bob_client = client_of(sample_app, bob)
    # the reader of the memo reads, lists and downloads its attachment, not its cover
    assert bob_client.get(f'{FILES}{attachment}/').status_code == 200
    assert ids(bob_client.get(FILES)) == [str(attachment)]
    response = bob_client.get(f'{FILES}{attachment}/download/')
    assert response.status_code == 200, response.text
    assert response.content == b'The plan.'
    assert bob_client.get(f'{FILES}{cover}/').status_code == 404
    assert bob_client.get(f'{FILES}{cover}/download/').status_code == 404
    response = bob_client.get(f'{MEMOS}{memo.pk}/', params={'include': 'attachment,cover'})
    assert [str(it['id']) for it in response.json()['included']] == [attachment]

    # a user who does not see the memo sees neither file
    carol_client = client_of(sample_app, carol)
    assert carol_client.get(f'{MEMOS}{memo.pk}/').status_code == 404
    assert carol_client.get(f'{FILES}{attachment}/').status_code == 404
    assert carol_client.get(f'{FILES}{attachment}/download/').status_code == 404
    assert ids(carol_client.get(FILES)) == []

    # the visibility follows the object
    memo.readers.remove(bob)
    assert bob_client.get(f'{FILES}{attachment}/').status_code == 404
    assert ids(alice_client.get(FILES)) == sorted([str(attachment), str(cover)])


@pytest.mark.django_db(transaction=True)
def test_the_visible_files_are_the_union_of_the_declaring_routes(sample_app, media):
    """A file is visible through every route set that declares it: the memo, the board."""
    alice, bob, carol, dave = (make_user(it) for it in ('alice', 'bob', 'carol', 'dave'))
    shared = upload_id(client_of(sample_app, alice), 'shared.txt')
    board_only = upload_id(client_of(sample_app, alice), 'board.txt')
    memo = Memo().objects.create(title='Memo', owner=alice, attachment_id=shared)
    memo.readers.add(bob)
    board = Board().objects.create(title='Board')
    board.members.add(carol)
    board.files.add(shared, board_only)

    def visible(user):
        return sorted(ids(client_of(sample_app, user).get(FILES)))

    assert visible(bob) == [str(shared)]
    assert visible(carol) == sorted([str(shared), str(board_only)])
    assert visible(dave) == []
    files = FileUpload.objects.all()
    restricted = FileUploadRouteSet.restrict_queryset(files, CrudAccessAction.VIEW, user=carol)
    assert sorted(str(it.pk) for it in restricted) == visible(carol)


@pytest.mark.django_db(transaction=True)
def test_a_user_links_only_his_own_files(sample_app, media):
    """
    A visible file of another user is not linked (422 ERR_RELATION_LINK), an invisible one
    is 403 as before; his own file links; a kept link is not checked.
    """
    alice, bob = make_user('alice'), make_user('bob')
    alice_client, bob_client = client_of(sample_app, alice), client_of(sample_app, bob)
    visible = upload_id(alice_client, 'visible.txt')
    hidden = upload_id(alice_client, 'hidden.txt')
    own = upload_id(bob_client, 'own.txt')
    memo = Memo().objects.create(title='Memo', owner=alice, attachment_id=visible)
    memo.readers.add(bob)
    board = Board().objects.create(title='Board')
    board.members.add(bob)
    assert bob_client.get(f'{FILES}{visible}/').status_code == 200

    response = bob_client.post(NOTES, json_data=note_body('Copy', visible))
    assert_not_linkable(response, '/data/relationships/attachment')
    response = bob_client.post(NOTES, json_data=note_body('Steal', hidden))
    assert response.status_code == 403, response.text
    assert response.json()['errors'][0]['code'] == 'ERR_RELATION_ACCESS'
    assert not apps.get_model('notes.Note').objects.exists()

    url = f'{BOARDS}{board.pk}/relationships/files'
    response = bob_client.post(url, json_data=relationship('uploadable.file_upload', own, visible, many=True))
    assert_not_linkable(response, '/data/1')
    response = bob_client.patch(
        f'{BOARDS}{board.pk}/',
        json_data={
            'data': {
                'type': 'notes.board',
                'id': str(board.pk),
                'relationships': {'files': relationship('uploadable.file_upload', visible, many=True)},
            }
        },
    )
    assert_not_linkable(response, '/data/relationships/files')
    assert list(board.files.all()) == []

    response = bob_client.post(url, json_data=relationship('uploadable.file_upload', own, many=True))
    assert response.status_code == 204, response.text
    assert [it.pk for it in board.files.all()] == [int(own)]
    response = bob_client.post(NOTES, json_data=note_body('Own', own))
    assert response.status_code == 201, response.text

    # the reader changes the memo and keeps the attachment of its owner
    response = bob_client.patch(
        f'{MEMOS}{memo.pk}/',
        json_data={
            'data': {
                'type': 'notes.memo',
                'id': str(memo.pk),
                'attributes': {'title': 'Memo 2'},
                'relationships': {'attachment': relationship('uploadable.file_upload', visible)},
            }
        },
    )
    assert response.status_code == 200, response.text

    files = FileUpload.objects.all()
    linkable = FileUploadRouteSet.restrict_queryset(
        files, CrudAccessAction.VIEW, user=bob, link=True
    )
    assert [str(it.pk) for it in linkable] == [str(own)]
    changeable = FileUploadRouteSet.restrict_queryset(files, CrudAccessAction.CHANGE, user=bob)
    assert [str(it.pk) for it in changeable] == [str(own)]


@pytest.mark.django_db(transaction=True)
def test_download_checks_the_access(sample_app, media):
    owner, stranger = make_user('owner'), make_user('stranger')
    client = client_of(sample_app, owner)
    text = upload_id(client, 'report.html', b'<script>alert(1)</script>')
    image = upload_id(client, 'photo.png', b'\x89PNG\r\n\x1a\n')

    assert client_of(sample_app).get(f'{FILES}{text}/download/').status_code == 401
    assert client_of(sample_app, stranger).get(f'{FILES}{text}/download/').status_code == 404
    assert client.get(f'{FILES}0/download/').status_code == 404

    response = client.get(f'{FILES}{text}/download/')
    assert response.status_code == 200, response.text
    assert response.content == b'<script>alert(1)</script>'
    # served as a download whatever the client declared, never run on the API origin
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['content-disposition'] == 'attachment; filename="report.html"'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-security-policy'] == 'sandbox'
    assert response.headers['cache-control'] == 'private, no-store'

    response = client.get(f'{FILES}{image}/download/')
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['content-disposition'] == 'inline; filename="photo.png"'

    # a file missing from the storage
    item = FileUpload.objects.get(pk=text)
    item.file.storage.delete(item.file.name)
    assert client.get(f'{FILES}{text}/download/').status_code == 404


@pytest.mark.django_db(transaction=True)
def test_create_for_stores_a_generated_file(sample_app, media):
    """
    `create_for` stores the bytes the server generated for an owner; the readers of the
    object that references it see it through `files_visible`.
    """
    owner, reader = make_user('owner'), make_user('reader')

    item = FileUpload.objects.create_for(owner, 'certificate-7.pdf', b'%PDF-1.7 ...')

    item.refresh_from_db()
    assert (item.author, item.name, item.extension, item.size) == (owner, 'certificate-7.pdf', 'pdf', 12)
    assert item.file.name.startswith('files/fileupload/') and item.file.name.endswith('.pdf')
    with item.file.open('rb') as f:
        assert f.read() == b'%PDF-1.7 ...'
    assert ids(client_of(sample_app, owner).get(FILES)) == [str(item.pk)]
    assert ids(client_of(sample_app, reader).get(FILES)) == []

    memo = Memo().objects.create(title='Certificate', owner=owner, attachment=item)
    memo.readers.add(reader)
    response = client_of(sample_app, reader).get(f'{FILES}{item.pk}/download/')
    assert response.content == b'%PDF-1.7 ...'
    assert response.headers['content-type'] == 'application/pdf'

    # a text, and a file of nobody outside a request: visible only through the objects
    report = FileUpload.objects.create_for(None, 'report.csv', 'a;b\n1;2\n')
    assert report.author is None
    assert report.file.read() == b'a;b\n1;2\n'


def test_files_visible_errors(sample_app):
    """`uploadable.E001`: the names of files_visible are relations to the uploaded files."""
    assert check_files_visible(None) == []

    def errors(files_visible, model=None):
        route = SimpleNamespace(files_visible=files_visible, model=model or Memo())
        return files_visible_errors(route)

    assert errors(('attachment', 'cover')) == []
    assert errors(['files'], Board()) == []
    assert errors('attachment') == ["is 'attachment', not a tuple of field names"]
    assert errors(('title', 'owner', 'missing')) == [
        f"{name!r} is not a relation of notes.Memo to a model of uploaded files whose default "
        'route is FileUploadRouteSet'
        for name in ('title', 'owner', 'missing')
    ]
    # a relation to a model that is not a JSON:API model (no default route)
    assert errors(('content_type',), apps.get_model('auth.Permission')) == [
        "'content_type' is not a relation of auth.Permission to a model of uploaded files "
        'whose default route is FileUploadRouteSet'
    ]
    abstract = SimpleNamespace(files_visible=('attachment',), model=Memo(), abstract=True)
    assert files_visible_errors(abstract) == [
        'is declared on an abstract route class (or one without a model): it is not inherited'
    ]


def test_only_the_declaring_route_sets_count(sample_app, monkeypatch):
    """
    A subclass of a declaring route set does not inherit `files_visible`; the declarations
    are resolved once the application is loaded.
    """
    from notes.routes import BoardRouteSet, MemoRouteSet

    # a route class becomes the default route of its model: restore it
    monkeypatch.setattr(Memo(), '_default_route', Memo().get_default_route())

    class MemoArchiveRouteSet(MemoRouteSet):
        @classmethod
        def members_q(cls, user):
            return Q()

    files_visible_cache_clear()
    declared = files_visible_routes(FileUpload)
    assert MemoArchiveRouteSet.files_visible == ('attachment',)
    assert set(declared) == {(MemoRouteSet, ('attachment',)), (BoardRouteSet, ('files',))}
    assert files_visible_routes(FileUpload) is declared
    files_visible_cache_clear()
    assert files_visible_routes(FileUpload) is not declared
