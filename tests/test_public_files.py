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
The files of public objects (2.9): an anonymous user reads and downloads the files of
`files_visible` of the objects a registered route set that serves him (its item without
`get_user_required`) shows him (its `restrict_queryset` for VIEW with an anonymous user);
any other file is 404, as one that does not exist. The sample: `notes.Poster` with
`photo` (declared) and `scan` (not), `PosterRouteSet` shows a guest the published posters.
"""

from django.apps import apps

from fastapi import Depends, FastAPI, HTTPException

import pytest

from bazis.contrib.uploadable.checks import check_public_files
from bazis.contrib.uploadable.models import FileUpload
from bazis.contrib.uploadable.routes import (
    AnonymousThrottle,
    FileUploadRouteSet,
    anonymous_files,
    files_public_q,
    files_visible_cache_clear,
    route_serves_anonymous,
)
from bazis.contrib.users import get_anonymous_user_model
from bazis.contrib.users.routes_abstract import UserRequiredRouteBase, UserRouteBase
from bazis.contrib.users.service import get_user_from_token, get_user_required
from bazis.core.routes_abstract.initial import inject_make, route_declare
from bazis.core.routes_abstract.jsonapi import RestrictedQsRouteMixin
from bazis.core.routing import BazisRoute
from bazis.core.schemas import CrudAccessAction

from .test_anonymous_upload import PNG, guest_upload, pk_of
from .test_files_visible import MEMOS, Memo
from .test_uploadable import FILES, client_of, make_user, upload


POSTERS = '/api/v1/notes/poster/'


def Poster():  # noqa: N802
    return apps.get_model('notes.Poster')


def upload_id(client, filename='photo.png', content=PNG):
    response = upload(client, filename, content)
    assert response.status_code == 201, response.text
    return str(response.json()['data']['id'])


@pytest.fixture
def caches():
    """The route sets are resolved again before and after the test."""
    files_visible_cache_clear()
    yield
    files_visible_cache_clear()


@pytest.fixture
def catalog(sample_app, media, caches):
    """A published poster with its photo and scan, a draft with its photo, an orphan."""
    alice = make_user('alice')
    client = client_of(sample_app, alice)
    files = {
        name: upload_id(client, f'{name}.png')
        for name in ('photo', 'scan', 'draft', 'orphan')
    }
    poster = Poster().objects.create(
        title='Concert', published=True, photo_id=files['photo'], scan_id=files['scan']
    )
    draft = Poster().objects.create(title='Draft', photo_id=files['draft'])
    return {'alice': alice, 'poster': poster, 'draft_poster': draft, **files}


def app_of(*route_classes) -> FastAPI:
    """An application that registers the route classes, as the core does."""
    app = FastAPI()
    for route_cls in route_classes:
        router = route_cls.as_router()
        router.routes_cast(BazisRoute)
        app.include_router(router)
    return app


@pytest.fixture
def poster_route(monkeypatch, caches):
    """
    Makes route classes of the posters: a route class becomes the default route of its
    model, restored after the test; the declarations of `files_visible` the test adds
    (`monkeypatch`) are removed with it.
    """
    for model in (Poster(), Memo(), FileUpload):
        monkeypatch.setattr(model, '_default_route', model.get_default_route())
    made = []

    def make(base, files_visible=None, model=None, **attrs):
        made.append(base)
        attrs.setdefault('model', model or Poster())
        attrs.setdefault('__module__', __name__)
        route_cls = type(f'PosterTest{len(made)}RouteSet', (base,), attrs)
        if files_visible is not None:
            monkeypatch.setattr(route_cls, 'files_visible', files_visible, raising=False)
        return route_cls

    return make


@pytest.mark.django_db(transaction=True)
def test_a_guest_reads_the_files_of_the_public_objects(sample_app, catalog):
    guest = client_of(sample_app)

    response = guest.get(f'{FILES}{catalog["photo"]}/')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert (str(data['id']), data['attributes']['name']) == (catalog['photo'], 'photo.png')
    assert 'author' not in data.get('relationships', {})
    response = guest.get(f'{FILES}{catalog["photo"]}/download/')
    assert response.status_code == 200, response.text
    assert response.content == PNG
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['content-disposition'] == 'inline; filename="photo.png"'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'

    # include on the public object: only its declared file; the relationship keeps the scan
    response = guest.get(f'{POSTERS}{catalog["poster"].pk}/', params={'include': 'photo,scan'})
    assert response.status_code == 200, response.text
    assert [str(it['id']) for it in response.json()['included']] == [catalog['photo']]
    relationships = response.json()['data']['relationships']
    assert str(relationships['scan']['data']['id']) == catalog['scan']


@pytest.mark.django_db(transaction=True)
def test_a_guest_reads_no_other_file(sample_app, catalog):
    """
    The scan (not declared), the photo of a draft (a poster a guest does not see) and a
    file no object references are 404, the same answer as a file that does not exist.
    """
    guest = client_of(sample_app)
    assert guest.get(f'{POSTERS}{catalog["draft_poster"].pk}/').status_code == 404

    missing = {
        suffix: guest.get(f'{FILES}999999999/{suffix}') for suffix in ('', 'download/')
    }
    assert {it.status_code for it in missing.values()} == {404}
    for name in ('scan', 'draft', 'orphan'):
        for suffix, response in missing.items():
            hidden = guest.get(f'{FILES}{catalog[name]}/{suffix}')
            assert (hidden.status_code, hidden.json()) == (404, response.json()), name

    # the users are unchanged: they see the drafts, so their photos, not the scan
    bob = client_of(sample_app, make_user('bob'))
    assert bob.get(f'{FILES}{catalog["draft"]}/download/').status_code == 200
    assert bob.get(f'{FILES}{catalog["scan"]}/').status_code == 404
    assert bob.get(f'{FILES}{catalog["orphan"]}/').status_code == 404


@pytest.mark.django_db(transaction=True)
def test_a_guest_lists_and_writes_nothing(sample_app, catalog):
    """Only the item and the download are public: the rest is 401, the writes 405."""
    guest = client_of(sample_app)
    photo = catalog['photo']

    for path in ('', '_id/', 'schema_list/', 'schema_create/', f'{photo}/schema_retrieve/'):
        assert guest.get(f'{FILES}{path}').status_code == 401, path
    assert upload(guest).status_code == 401
    body = {'data': {'id': photo, 'type': 'uploadable.file_upload', 'attributes': {'name': 'x'}}}
    assert guest.patch(f'{FILES}{photo}/', json_data=body).status_code == 405
    assert guest.delete(f'{FILES}{photo}/').status_code == 405
    assert FileUpload.objects.get(pk=photo).name == 'photo.png'

    # declared public in the OpenAPI document: the item and the download, nothing else
    public = {
        (path, method): operation['x-bazis']['public']
        for path, item in sample_app.openapi()['paths'].items()
        if path.startswith(FILES)
        for method, operation in item.items()
    }
    assert {key for key, value in public.items() if value} == {
        (f'{FILES}{{item_id}}/', 'get'),
        (f'{FILES}{{item_id}}/download/', 'get'),
    }


@pytest.mark.django_db(transaction=True)
def test_an_anonymous_user_only_views_the_public_files(sample_app, catalog):
    """
    `restrict_queryset` for an anonymous user (or none): the public files to view, none to
    link or for another action, whatever he sees.
    """
    files = FileUpload.objects.all()
    anonymous = get_anonymous_user_model()()

    def restricted(access_action, **kwargs):
        return [
            str(it.pk)
            for it in FileUploadRouteSet.restrict_queryset(files, access_action, **kwargs)
        ]

    assert restricted(CrudAccessAction.VIEW, user=anonymous) == [catalog['photo']]
    assert restricted(CrudAccessAction.VIEW) == [catalog['photo']]
    assert restricted(CrudAccessAction.VIEW, user=anonymous, link=True) == []
    for action in (CrudAccessAction.CHANGE, CrudAccessAction.ADD, CrudAccessAction.DELETE):
        assert restricted(action, user=anonymous) == []
        assert restricted(action) == []
    # a user: his own files and the visible ones, as before
    assert sorted(restricted(CrudAccessAction.VIEW, user=catalog['alice'])) == sorted(
        catalog[it] for it in ('photo', 'scan', 'draft', 'orphan')
    )


@pytest.mark.django_db(transaction=True)
def test_a_subclass_narrows_the_public_files(sample_app, catalog, monkeypatch):
    """
    The bases after `FileUploadRouteSet` (bazis-permit) narrow the public files too: its
    `restrict_queryset` calls theirs with the anonymous user.
    """
    monkeypatch.setattr(FileUpload, '_default_route', FileUpload.get_default_route())

    class NoGuestRouteBase(RestrictedQsRouteMixin):
        abstract = True

        @classmethod
        def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
            return qs if getattr(user, 'is_authenticated', False) else qs.none()

    class NarrowFileRouteSet(FileUploadRouteSet, NoGuestRouteBase):
        pass

    def visible(route_cls, user):
        files = FileUpload.objects.all()
        return [str(it.pk) for it in route_cls.restrict_queryset(files, CrudAccessAction.VIEW, user=user)]

    for user in (get_anonymous_user_model()(), None):
        assert visible(FileUploadRouteSet, user) == [catalog['photo']]
        assert visible(NarrowFileRouteSet, user) == []
    assert len(visible(NarrowFileRouteSet, catalog['alice'])) == 4


@pytest.mark.django_db(transaction=True)
def test_the_files_of_a_route_set_that_requires_a_user_are_not_public(
    sample_app, catalog, monkeypatch
):
    """
    `MemoRouteSet` (`UserRequiredRouteBase`) declares `files_visible`: even if it showed
    all its memos (no `restrict_queryset` of its own), a guest reads none of their files.
    """
    from notes.routes import MemoRouteSet

    monkeypatch.setattr(
        MemoRouteSet, 'restrict_queryset', classmethod(lambda cls, qs, *args, **kwargs: qs)
    )
    attachment = upload_id(client_of(sample_app, catalog['alice']), 'memo.txt', b'Memo.')
    Memo().objects.create(title='Memo', attachment_id=attachment)

    assert route_serves_anonymous(MemoRouteSet) is False
    guest = client_of(sample_app)
    assert guest.get(f'{MEMOS}').status_code == 401
    assert guest.get(f'{FILES}{attachment}/').status_code == 404
    assert guest.get(f'{FILES}{attachment}/download/').status_code == 404
    # a user who is not a reader sees it now: the memos are all shown to the users
    carol = client_of(sample_app, make_user('carol'))
    assert carol.get(f'{FILES}{attachment}/').status_code == 200


@pytest.mark.django_db(transaction=True)
def test_an_anonymous_upload_is_public_only_with_a_public_object(sample_app, media, settings):
    settings.BAZIS_FILE_UPLOAD_ANONYMOUS = True
    settings.BAZIS_FILE_UPLOAD_MAX_SIZE = 1024
    item = pk_of(guest_upload(sample_app))
    guest = client_of(sample_app)

    assert guest.get(f'{FILES}{item}/').status_code == 404
    assert guest.get(f'{FILES}{item}/download/').status_code == 404
    poster = Poster().objects.create(title='Lost cat', photo_id=item)
    assert guest.get(f'{FILES}{item}/download/').status_code == 404
    poster.published = True
    poster.save()
    assert guest.get(f'{FILES}{item}/download/').content == PNG


def test_route_serves_anonymous(sample_app, poster_route, monkeypatch):
    """
    By the dependencies FastAPI runs for the registered item of the route class, not by
    `auth_required`; a route class no router registers serves nobody.
    """
    from notes.routes import BoardRouteSet, MemoRouteSet, NoteRouteSet, PosterRouteSet

    assert route_serves_anonymous(PosterRouteSet) is True
    assert route_serves_anonymous(FileUploadRouteSet) is True
    for route_cls in (NoteRouteSet, MemoRouteSet, BoardRouteSet):
        assert route_serves_anonymous(route_cls) is False, route_cls

    unregistered = poster_route(PosterRouteSet)
    assert route_serves_anonymous(unregistered) is False

    class InjectStaff:
        user: object = Depends(get_user_required)

    # the class says that the user is optional, a dependency of its own requires him
    staff = poster_route(UserRouteBase, InjectUser=inject_make()(InjectStaff))
    assert staff.auth_required is False
    required = poster_route(UserRequiredRouteBase)
    optional = poster_route(UserRouteBase)
    app = app_of(staff, required, optional)
    monkeypatch.setattr('bazis.core.introspect.loaded_app', lambda: app)
    files_visible_cache_clear()
    assert route_serves_anonymous(staff) is False
    assert route_serves_anonymous(required) is False
    assert route_serves_anonymous(optional) is True
    # registered elsewhere, not in the application
    assert route_serves_anonymous(PosterRouteSet) is False


def test_route_serves_anonymous_is_kept_once_the_application_is_loaded(
    sample_app, poster_route, monkeypatch
):
    from notes.routes import PosterRouteSet

    route_cls = poster_route(UserRouteBase)
    app = app_of(route_cls)
    loaded = {'app': None}
    monkeypatch.setattr('bazis.core.introspect.loaded_app', lambda: loaded['app'])

    # before the application is loaded: nothing serves, nothing is kept
    assert route_serves_anonymous(PosterRouteSet) is False
    loaded['app'] = sample_app
    assert route_serves_anonymous(PosterRouteSet) is True
    assert route_serves_anonymous(route_cls) is False
    # kept: registered later, it is seen once the cache is cleared
    loaded['app'] = app
    assert route_serves_anonymous(route_cls) is False
    assert route_serves_anonymous(PosterRouteSet) is True
    files_visible_cache_clear()
    assert route_serves_anonymous(route_cls) is True
    assert route_serves_anonymous(PosterRouteSet) is False


@pytest.mark.django_db(transaction=True)
def test_an_unregistered_declaration_makes_no_file_public(
    sample_app, catalog, poster_route
):
    """
    A route class that serves guests by its bases but that no router registers: its
    `files_visible` shows the users their files, not the guests.
    """
    from notes.routes import PosterRouteSet

    poster_route(PosterRouteSet, files_visible=('scan',))
    files_visible_cache_clear()
    assert client_of(sample_app).get(f'{FILES}{catalog["scan"]}/').status_code == 404
    bob = client_of(sample_app, make_user('bob'))
    assert bob.get(f'{FILES}{catalog["scan"]}/').status_code == 200


def test_anonymous_files(sample_app, caches, monkeypatch):
    """Whether guests read some files: a route set that serves them declares files_visible."""
    assert anonymous_files() is True
    monkeypatch.setattr('bazis.core.introspect.loaded_app', lambda: app_of())
    files_visible_cache_clear()
    assert anonymous_files() is False


def test_public_files_warning(sample_app, poster_route, monkeypatch):
    """
    `uploadable.W003`: a route set that serves guests and declares `files_visible` without
    restricting its objects, unless it declares `permit_public = True`.
    """
    from notes.routes import PosterRouteSet

    assert check_public_files(None) == []
    everyone = poster_route(UserRouteBase, files_visible=('photo',))
    public = poster_route(UserRouteBase, files_visible=('photo',), permit_public=True)
    required = poster_route(UserRequiredRouteBase, files_visible=('photo',))
    app = app_of(everyone, public, required, PosterRouteSet)
    monkeypatch.setattr('bazis.core.introspect.loaded_app', lambda: app)
    files_visible_cache_clear()

    messages = check_public_files(None)
    assert [(it.id, it.obj) for it in messages] == [('uploadable.W003', everyone)]
    assert 'guests read the files of files_visible of all its objects' in messages[0].msg


@pytest.mark.django_db(transaction=True)
def test_the_guests_are_throttled_by_ip(sample_app, catalog, settings):
    """The guests read the files at `BAZIS_THROTTLE_PUBLIC` per IP address, the users freely."""
    settings.BAZIS_THROTTLE_PUBLIC = '2/hour'
    guest = client_of(sample_app)

    for suffix in ('', 'download/'):
        url = f'{FILES}{catalog["photo"]}/{suffix}'
        assert [guest.get(url).status_code for _ in range(3)] == [200, 200, 429], suffix
        response = guest.get(url)
        assert response.json()['errors'][0]['code'] == 'ERR_THROTTLED'
        assert int(response.headers['Retry-After']) > 0
    user = client_of(sample_app, catalog['alice'])
    for suffix in ('', 'download/'):
        url = f'{FILES}{catalog["photo"]}/{suffix}'
        assert [user.get(url).status_code for _ in range(3)] == [200, 200, 200], suffix


def anonymous_throttles(route_cls) -> int:
    dependencies = route_cls.routes_ctx['action_retrieve'].route_params.dependencies or ()
    return sum(isinstance(getattr(it, 'dependency', None), AnonymousThrottle) for it in dependencies)


def marker():
    """A dependency a subclass declares on the item."""


def test_a_subclass_keeps_the_dependencies_of_its_item(poster_route):
    """
    The item of a subclass of `FileUploadRouteSet` is public with one throttle of the
    guests, and keeps the dependencies the subclass declares.
    """
    assert anonymous_throttles(FileUploadRouteSet) == 1
    # The redeclaration in the class body is the pattern that keeps the dependency here
    # but is not for applications: the route of the body is registered before `/_id/` and
    # the schema routes and takes their paths (a core behavior, bazis 2.25+ plans a fix).
    # Applications use `inject_make(CrudApiAction.RETRIEVE)` or `cls_init`.
    declaring = poster_route(
        FileUploadRouteSet,
        model=FileUpload,
        action_retrieve=route_declare(
            FileUploadRouteSet.action_retrieve, dependencies=[Depends(marker)]
        ),
    )
    inheriting = poster_route(declaring, model=FileUpload)
    for route_cls in (declaring, inheriting):
        route = route_cls.routes_ctx['action_retrieve']
        assert route.public is True
        assert [it.dependency for it in route.route_params.dependencies][0] is marker
        assert anonymous_throttles(route_cls) == 1


def user_or_401(user=Depends(get_user_from_token)):
    """A user required without `get_user_required`."""
    if user is None:
        raise HTTPException(status_code=401)
    return user


@inject_make()
class InjectOwnUser:
    user: object = Depends(user_or_401)


@pytest.mark.django_db(transaction=True)
def test_a_failing_restrict_queryset_hides_only_its_files(
    sample_app, catalog, poster_route, monkeypatch, caplog
):
    """
    A route set that requires the user by a dependency of its own counts as serving
    guests; its `restrict_queryset` (`owner=user`) fails for the anonymous user: its files
    are 404 for a guest with a warning, the files of the other public route sets stay
    public, its owner reads them as before.
    """
    from notes.routes import MemoRouteSet

    def by_owner(cls, qs, access_action, user=None, **kwargs):
        return qs.filter(owner=user)

    broken = poster_route(
        UserRouteBase,
        files_visible=('attachment',),
        model=Memo(),
        InjectUser=InjectOwnUser,
        restrict_queryset=classmethod(by_owner),
    )
    app = FastAPI()
    app.include_router(sample_app.router)
    app.include_router(broken.as_router())
    monkeypatch.setattr('bazis.core.introspect.loaded_app', lambda: app)
    files_visible_cache_clear()
    assert route_serves_anonymous(broken) is True
    assert route_serves_anonymous(MemoRouteSet) is False

    bob = make_user('bob')
    attachment = upload_id(client_of(sample_app, catalog['alice']), 'memo.txt', b'Memo.')
    Memo().objects.create(title='Memo', owner=bob, attachment_id=attachment)
    guest = client_of(sample_app)
    name = f'tests.test_public_files.{broken.__qualname__}.restrict_queryset failed'
    assert broken.__module__ == 'tests.test_public_files'
    for suffix in ('', 'download/'):
        caplog.clear()
        with caplog.at_level('WARNING', logger='bazis.contrib.uploadable.routes'):
            response = guest.get(f'{FILES}{attachment}/{suffix}')
        missing = guest.get(f'{FILES}999999999/{suffix}')
        assert (response.status_code, response.json()) == (404, missing.json()), suffix
        warned = [it.levelname for it in caplog.records if name in it.getMessage()]
        assert warned and set(warned) == {'WARNING'}, suffix
        # the other public route sets still serve their files
        assert guest.get(f'{FILES}{catalog["photo"]}/{suffix}').status_code == 200
    assert client_of(sample_app, bob).get(f'{FILES}{attachment}/download/').content == b'Memo.'
    # contract against execution: guests are said to read files through it
    assert anonymous_files() is True

    # the failure is not kept: a fixed rule shows the file on the next request
    def owner_or_none(cls, qs, access_action, user=None, **kwargs):
        return qs.filter(owner=user) if user.is_authenticated else qs.none()

    monkeypatch.setattr(broken, 'restrict_queryset', classmethod(owner_or_none))
    caplog.clear()
    assert guest.get(f'{FILES}{attachment}/').status_code == 404
    assert not [it for it in caplog.records if name in it.getMessage()]
    monkeypatch.setattr(broken, 'restrict_queryset', classmethod(lambda cls, qs, *a, **k: qs))
    assert guest.get(f'{FILES}{attachment}/').status_code == 200


def test_anonymous_files_counts_a_failing_route_set(sample_app, poster_route, monkeypatch):
    """
    Only a route set whose `restrict_queryset` fails for guests serves them: the contract
    says that they read files (a known difference with what they read).
    """
    broken = poster_route(
        UserRouteBase,
        files_visible=('attachment',),
        model=Memo(),
        InjectUser=InjectOwnUser,
        restrict_queryset=classmethod(lambda cls, qs, *args, user=None, **kw: qs.filter(owner=user)),
    )
    app = app_of(broken)
    monkeypatch.setattr('bazis.core.introspect.loaded_app', lambda: app)
    files_visible_cache_clear()
    assert anonymous_files() is True
    assert files_public_q(FileUpload) is None
