# bazis-uploadable — guide for AI agents

File uploads for Bazis: the model `uploadable.FileUpload` (a file in a Django storage with
its name, extension and author) and a JSON:API route that accepts the file as multipart form
data. Other models can reference uploaded files with a foreign key to `uploadable.FileUpload`.
Needs bazis-users and bazis-author: a file has an `author`, the user who uploaded it.

### The sections

Read a section with `package_guide("bazis-uploadable", "<section>")` when the step at hand
needs it; `guide_search` finds the part of a section that answers a question. A product
with files needs Setup, Access and Serving; a public form with files (guests attach
photos) also Anonymous uploads.

| Section | Read it when |
|---|---|
| Setup | you install it: the apps, the storage, the size limit, the router |
| Access | you decide who reads and links the files: the own files, `files_visible` on the route sets of the objects, the files of public objects for guests, linking files to objects, a subclass with a rule of its own, bazis-permit |
| Upload | a client uploads a file: the multipart request and its response |
| Anonymous uploads | guests upload files for a public action: the settings, what a guest reads, attaching the files in the action, the clean-up, the proxy |
| Download | a client reads a file (with its token; a guest a public file): `/{id}/download/` and its headers |
| Files the server generates | the server stores a file (a PDF, an export): `create_for`, a PDF with non-Latin text |
| Serving | you deploy: the media host, the headers, S3, private files and the public media URL |
| Models | a model of files of your own, the fields, a migration cycle with the user model, the storage paths |
| Rules | before you write the code, once |

## Setup

- `BS_INSTALLED_APPS` includes `bazis.contrib.uploadable` (the model and its migrations:
  run `migrate`) and the user model of bazis-users (`BS_AUTH_USER_MODEL`), e.g.
  `bazis.contrib.users` with `users.User`. If `BS_BAZIS_APPS` is set, list
  `bazis.contrib.uploadable`, `bazis.contrib.author` and `bazis.contrib.users` there too.
- Storage: `BS_BAZIS_STORAGE_FILE_UPLOAD` is the dotted path of a Django storage class,
  created without arguments (e.g. an S3 storage configured by its own settings). Empty
  (default): `FileSystemStorage` in `MEDIA_ROOT` (`BS_MEDIA_ROOT`). The class is imported
  once, when the models are loaded; the field uses a callable storage, so changing the
  setting needs no migration. An S3 storage of django-storages (`storages.backends.s3`,
  `s3boto3`, or a subclass) gets `S3SafeServingMixin` automatically (see Serving).
- `BS_BAZIS_FILE_UPLOAD_MAX_SIZE`: the maximum file size in bytes, `0` (default) = no
  limit. A larger file is rejected with 413 and the error code `ERR_FILE_TOO_LARGE`. The
  check runs after the whole request body is received: also limit the request body size
  on the reverse proxy.
- `BS_BAZIS_FILE_UPLOAD_ANONYMOUS` (off by default) and its settings: see Anonymous
  uploads.
- Routes: `bazis.contrib.uploadable.router` registers `FileUploadRouteSet`.

## Access

`FileUploadRouteSet` (`AuthorRequiredRouteBase` of bazis-author) requires a user (401
without a token), except the upload when anonymous uploads are on (Anonymous uploads) and
the item and the download, which serve a guest the files of public objects (2.9, below):

- create: the user uploads a file and becomes its `author` (a client cannot set it);
- list (`/`, `/_id/`), retrieve and download (`/{id}/download/`): the files whose `author`
  is the user and the files of the objects he sees through a route set that declares them
  in `files_visible` (below); another file is 404;
- retrieve and download without a token: the files of public objects (below); another
  file is 404, the same answer as a file that does not exist; the list, `/_id/`, the
  schema routes and the upload (with anonymous uploads off) stay 401;
- no update, no delete (405) and no relationships endpoints: a file referenced by the
  objects of other users stays as it was.

`FileUploadRouteSet` is the default route of `uploadable.FileUpload`: its classmethod
`restrict_queryset` (for an anonymous user the files of public objects to view, none to
link or for another action; the authenticated user of the request
`UserMixin.CTX_USER_REQUEST` when the caller passes no user) is also what the other
routes link and include (the core, Bazis 2.7). `CTX_USER_REQUEST` is set by the routes of
bazis-users (`UserRouteBase`) and its Django middleware: a route without a user (a plain
`JsonapiRouteBase`) does not set it, so there a logged-in user is anonymous for the files:
he sees only the files of public objects in `included` and cannot link even his own
files (403).

### Files visible with the objects that reference them

Declare on the route set of a model that references uploaded files the fields whose files
its readers read:

```python
class CertificateRouteSet(PermitRouteBase):
    model = apps.get_model('training.Certificate')
    files_visible = ('file',)     # a foreign key (or a many-to-many field) to the files
```

- A file is visible to a user if he sees an object that references it through one of the
  declared fields: the objects `restrict_queryset` of the declaring route set returns for
  `view` with that user (bazis-permit: his permissions). A route set that does not
  override `restrict_queryset` shows all its objects, so their files are visible to every
  logged-in user; one that restricts only in `get_queryset` must restrict in
  `restrict_queryset` too (the core rule).
- Several route sets (of the same or of other models) add up: a file is visible through
  any of them. The own files of the user stay visible.
- Visible means the list, the item, the download of the route of the files and
  `included` of the other routes. A guest reads only the files of public objects (below).
- The visibility follows the objects, not the rights to the field: when the user no
  longer sees the object, the file is 404 again; a field permission (bazis-permit) that
  hides the relation field of an object he sees does not hide its file. Declare only the
  fields whose files every reader of the object may read.
- Only a route class that declares `files_visible` in its own body counts: a subclass
  does not inherit it (declare it again), and `uploadable.E001` reports a declaration on
  an abstract route class. The declaration counts once the route class is defined (as the
  default routes of the core): declare it on the route sets you register. The
  declarations are resolved once the application is loaded; a test that defines a
  declaring route set later calls `files_visible_cache_clear()`
  (`bazis.contrib.uploadable.routes`).
- Forward relations of the model of the route (foreign key, one-to-one, many-to-many) to a
  model of files whose default route is `FileUploadRouteSet` or a subclass;
  `bazis_doctor` reports any other name (`uploadable.E001`, also for a string instead of a
  tuple).

This replaces a subclass of `FileUploadRouteSet` that unions the `restrict_queryset` of
several route sets.

### Files of public objects (guests)

A guest (no token) reads and downloads a file (2.9) if both hold:

1. a route set that declares the field in `files_visible` serves its item to guests: a
   router of the application registers its `action_retrieve`, and the dependencies
   FastAPI runs for it do not include `get_user_required` (checked on the registered
   route, not on `auth_required`). A route set of `UserRequiredRouteBase` never does; one
   of `UserRouteBase` (or a plain `JsonapiRouteBase`) does; a route class no router
   registers does not;
2. the object that references the file is among the objects that route set shows a guest:
   its `restrict_queryset(qs, view, user=<anonymous user of bazis-users>)`; all its
   objects if it does not override `restrict_queryset`.

```python
class PosterRouteSet(RestrictedQsRouteMixin, UserRouteBase):   # the user is optional
    model = apps.get_model('catalog.Poster')
    files_visible = ('photo',)

    @classmethod
    def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
        qs = super().restrict_queryset(qs, access_action, user=user, **kwargs)
        if UserMixin.authenticated_user(user) is None:
            return qs.filter(published=True)            # what a guest sees
        return qs
```

- Nothing else is declared: upgrading to 2.9 makes public the files of `files_visible`
  of the route sets that already serve guests. `bazis_doctor` warns
  (`uploadable.W003`) for such a route set without `restrict_queryset` of its own: the
  files of all its objects are public. Restrict its objects for a guest (none if they are
  private), require a user, or declare `permit_public = True` if all of them are public
  (the convention of bazis-permit, `permit.W002`: read by its name, bazis-uploadable does
  not depend on bazis-permit). With bazis-permit the roles for anonymous users decide
  (`PermitRouteBase` overrides `restrict_queryset`).
- A route set that requires the user by a dependency of its own (not `get_user_required`)
  is public for the files: its `restrict_queryset` gets the anonymous user. If it fails
  for him (e.g. `qs.filter(owner=user)`), its files are not public and a WARNING is
  logged (`<module>.<class>.restrict_queryset failed for an anonymous user`); the files of
  the other route sets stay public. Require the user with `get_user_required`, or return
  `qs.none()` when `not user.is_authenticated`. `anonymous_files()` still counts such a
  route set (it tells the declarations, not what its `restrict_queryset` returns).
- The item of `FileUploadRouteSet` and its subclasses is always public (`cls_init`
  declares it over a `public` a subclass sets; the dependencies a subclass declares
  stay): a subclass keeps guests out with its `restrict_queryset`. A subclass adds
  dependencies to the item with `inject_make(CrudApiAction.RETRIEVE)` or in its own
  `cls_init`, after `super().cls_init()`, with
  `route_declare(cls.routes_ctx['action_retrieve'], dependencies=[...])`. Do not
  redeclare `action_retrieve` in the class body: the route of the body is registered
  first and its path `/{item_id}/` then takes `/_id/` and the schema routes (a behavior
  of the core, planned to be fixed in bazis 2.25+).
- A guest reads the item (`/{id}/`) and the download (`/{id}/download/`) of the route of
  the files and `included` of the public routes (`?include=photo`); never the list
  (401), never a link (`restrict_queryset` is empty for him with `link=True` and for any
  action but `view`). Any other file is 404, the same answer as a missing file.
- His requests of the item and the download are limited by `BAZIS_THROTTLE_PUBLIC`
  (default `30/minute`) per IP address and route, the users are not counted: raise it for
  pages that show many files to guests. The download keeps `Cache-Control: private,
  no-store`: every view is a request.
- A logged-in user reads them as before, through `files_visible`; a plain `<img src>`
  without a token is a guest request: it shows a public file only.
- The bases after `FileUploadRouteSet` (bazis-permit) narrow the public files too: its
  `restrict_queryset` calls theirs with the anonymous user. A subclass that returns
  `qs.none()` for `user is None` itself keeps the files private for guests; one that
  returns `super().restrict_queryset(...)` for him (the pattern below) shows them.
- `route_serves_anonymous(route_cls)`, `files_public_q(model)` and `anonymous_files()`
  (whether guests read some files: what a frontend contract exports beside
  `anonymous_uploads()`) are in `bazis.contrib.uploadable.routes`; resolved once the
  application is loaded, `files_visible_cache_clear()` forgets them (a test).

### Linking files to objects

A relationship of another model (create, update, the relationships endpoints) links only
the files the user uploaded, whatever he sees: the core asks `restrict_queryset` for the
linked objects with `link=True` (Bazis 2.16) and the route of the files then returns only
the own files.

- a visible file of another user (through `files_visible`) fails with 422
  `ERR_RELATION_LINK`, a file he does not see with 403 `ERR_RELATION_ACCESS`, both pointing
  to `/data/relationships/<field>` (`/data/<j>` or `/data` on the relationships endpoints);
- an unchanged link is not checked: the reader of an object updates it and keeps the file
  of its author;
- `GET <object>/{id}/?include=<field>` leaves out the files the user does not see; the
  relationship keeps the identifier.

The route sets of the models that reference uploaded files need no checks of their own
(the sample route sets `notes.routes.NoteRouteSet`, `MemoRouteSet` and `BoardRouteSet`,
`tests/test_uploadable.py`, `tests/test_files_visible.py`). To link a file of the server
(a generated PDF) to an object, the server sets the relation itself (`create_for`, below).

### Other rules: a subclass

For a rule that is not "visible with an object" widen `restrict_queryset` in a subclass and
declare it the default route of the files (`default_route = True`, `bazis.W003`
otherwise). Keep the own files for `link` (tested in `tests/test_uploadable.py`):

```python
class FileRouteSet(FileUploadRouteSet):
    default_route = True

    @classmethod
    def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
        # the same user for the own files and the shared ones
        user = UserMixin.authenticated_user(user)
        own = super().restrict_queryset(qs, access_action, user=user, **kwargs)
        if user is None or kwargs.get('link'):
            return own
        return qs.filter(Q(pk__in=own.values('pk')) | Q(...))  # the shared files
```

Register such a subclass instead of the bundled router: it lists and reads the widened
files too (`get_queryset` applies `restrict_queryset`), at the same URLs (the resource path
of the model, `/uploadable/file_upload/`). Do not register both:

```python
# <app>/router.py
files_router = BazisRouter(tags=[_('Uploaded files')])
files_router.register(FileRouteSet.as_router())

# the root router, instead of router.register('bazis.contrib.uploadable.router')
router.register(files_router)
```

`FileUploadRouteSet` and its subclasses restrict the files with their own
`restrict_queryset`: `permit.W002` of bazis-permit does not apply to them from
bazis-permit 2.10 (with 2.9 the warning is a false positive). Do not declare
`permit_public = True` on them: it says that the files are public.

The package does not depend on bazis-permit. With it, a project subclasses
`FileUploadAbstract` with `PermitModelMixin` for its own model of files and registers a
subclass of `FileUploadRouteSet` that also inherits `PermitRouteBase`: the permissions
narrow the files of the author further (`restrict_queryset` of `FileUploadRouteSet` calls
the one of `PermitRouteBase` through `super()`); to let them decide alone, the subclass
overrides `restrict_queryset` with `super(FileUploadRouteSet, cls).restrict_queryset(...)`,
skipping the author filter. List `FileUploadRouteSet` first among the bases:
its `action_create` reads the multipart form. Keep custom file routes as restrictive.
Files without an `author` (uploaded before 2.5, in the admin or by scripts) are visible
only through `files_visible`.

## Upload

`POST <prefix>/uploadable/file_upload/` (the bundled router) with `multipart/form-data`:

- `file` (required): the file; `name` (optional): the file name, by default the file name
  of the uploaded file. The id is generated by the server (an `id` field is ignored).
- Response 201: a JSON:API item of type `uploadable.file_upload` with the attributes
  `file` (its URL in the storage), `name`, `extension` and `size` (bytes). A guest reads
  no `file` (Anonymous uploads).

## Anonymous uploads

Guests upload files for a public action (a request form with photos): the action takes
the ids the uploads answered in its body and attaches them to the object it creates. Off
by default; with it off the route is as before (401 without a token).

- `BS_BAZIS_FILE_UPLOAD_ANONYMOUS=true` turns it on, only with a size limit:
  `BS_BAZIS_FILE_UPLOAD_MAX_SIZE` > 0, otherwise guests upload nothing and `bazis_doctor`
  reports `uploadable.E002`. The upload route is then declared `public` (`x-bazis`), which
  is fixed when the routes are imported: restart the server after a change.
- `BS_BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES` (default `["image/jpeg","image/png","image/webp"]`,
  only these three are known): the type is recognized by the first bytes of the content,
  not by the name or the declared `Content-Type`; another content is 422 `ERR_FILE_TYPE`
  (`/file`). The file is stored with the extension of its type (`photo.html` with PNG
  content is stored and named `photo.png`).
- `BS_BAZIS_FILE_UPLOAD_ANONYMOUS_RATE` (default `60/hour`): the anonymous uploads per IP
  address (429 `ERR_THROTTLED`, `Retry-After`); a user who is logged in is not limited
  and uploads any type, as before. `BAZIS_THROTTLE_ENABLED` off turns the limit off.
- `BS_BAZIS_FILE_UPLOAD_ANONYMOUS_TTL` (hours, default 24): how long an upload can be
  attached; then `uploadable_clean_anonymous` deletes it unless something references it.
- A guest reads back a token as the id (`anonymous_token`: the id of the file signed with
  the time by `SECRET_KEY`), `name`, `extension` and `size` (no `file`, the URL), and
  reads no file afterwards: the list is 401 without a token, the item and the download
  404 (unless an object a guest sees references it: Files of public objects), and for
  the users an anonymous upload is nobody's (404) until an object references it and
  `files_visible` shows it to the readers of that object. It has no `author` and
  `uploaded_anonymously` is its time.
- An invalid or expired bearer token is 401, not a guest; the token of a user who is no
  longer active (or deleted) is a guest when anonymous uploads are on.
- A name or a file name with a control character (NUL...) is 422 `ERR_FILE_NAME`
  (`/name`, `/file`), for the users too, before anything is stored.
- For the clients: `anonymous_uploads()` (`bazis.contrib.uploadable.routes`: the setting
  with a size limit) and `BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES` are what a frontend contract
  exports (bazis-front 0.9+: `capabilities.uploadable.anonymous`, `anonymous_types`,
  beside `max_size`), so a public form offers the upload only when guests can upload.

A public form with files: the body takes the ids the uploads answered as `UploadedFileId`
(`bazis.contrib.uploadable.schemas`, a string whose JSON schema has
`x-relation: uploadable.file_upload`, so a client knows to upload a file). For a guest the
action takes the files with `FileUpload.objects.anonymous(data.photos)`: the tokens that
are valid and at most TTL old, of files without an author uploaded at most TTL ago; a bare
id, a forged or expired token and the files of users are left out. For a user it takes
his own files by their ids. It references them; the route set of the referencing model
declares `files_visible` for the staff who read them:

```python
from bazis.contrib.uploadable.schemas import UploadedFileId


class SubmitRequest(BaseModel):
    description: str
    photos: list[UploadedFileId] = []


# in a route set whose user is optional (UserRouteBase of bazis-users)
@http_post('/submit/', public=True, kind=RouteKind.OTHER, response_model=SubmitResponse,
           dependencies=[throttle('120/hour', key='ip')])
def action_submit(self, data: SubmitRequest, **kwargs):
    user = UserMixin.authenticated_user(self.inject.user)
    files = FileUpload.objects
    # a guest attaches anonymous uploads, a user his own files: never anonymous() for a user
    if user is None:
        photos = list(files.anonymous(data.photos))
    else:
        ids = [it for it in data.photos if it.isdigit()]
        photos = list(files.filter(pk__in=ids, author=user))
    if len(photos) != len(set(data.photos)):
        raise JsonApiBazisException([JsonApiBazisError(
            _('A photo is missing or expired'), loc=('photos',), code='ERR_PHOTO',
        )], status=422)
    order = self.model.objects.create(description=data.description)
    OrderPhoto.objects.bulk_create(OrderPhoto(order=order, file=it) for it in photos)
    return SubmitResponse(number=order.uniq_number)
```

Deploy:

- Run `python manage.py uploadable_clean_anonymous` periodically (cron, or a schedule of
  bazis-bg): it deletes the anonymous uploads older than the TTL that no object references
  (any foreign key, one-to-one or many-to-many field to the model of the files): each row
  locked and deleted only if it is still so (a reference inserted meanwhile waits and
  fails), then its file in the storage. A failure (a row, a
  file) is written to stderr, the others are deleted and the command exits with an error.
  A reference the database does not know (an id in a JSON field, a generic relation) does
  not keep a file.
- Limit the request body on the reverse proxy (nginx `client_max_body_size` a little
  above `BAZIS_FILE_UPLOAD_MAX_SIZE` for the upload path): the application checks the size
  after the whole body is received (spooled to disk), so without the proxy limit a guest
  still sends bodies of any size (a limit of the core before the body is read is planned
  for bazis 2.21+).
- The rate counts by `request.client.host`: behind a proxy, the proxy sends the address
  of the client (nginx `proxy_set_header X-Forwarded-For $remote_addr`, not the header the
  client sent) and uvicorn or gunicorn trusts only the proxy
  (`--proxy-headers --forwarded-allow-ips <proxy>`, `forwarded_allow_ips` of gunicorn),
  never `*` on a server clients reach directly; otherwise all guests share the count of
  the proxy, or pick their address.
- Serve the media from a separate origin (Serving): the upload is a valid image by its
  first bytes, not by the rest of its content.

Only the guest who uploaded a file has its token: within the TTL he can attach it again
(to another request; a token is not used up). Changing `SECRET_KEY` invalidates the tokens
of the uploads not attached yet, unless the old key stays in `SECRET_KEY_FALLBACKS` (the
tokens it signed stay valid). Attach anonymous uploads only to objects whose readers
may see what guests sent (the staff who process the requests).

## Download

`GET <prefix>/uploadable/file_upload/{id}/download/` (a user, the bearer token) streams the
content of a file the user sees (his own and the visible ones, as the item); without a
token the files of public objects (Access): 404 for another file or a file missing from
the storage. It is served as the media
host should serve it: the type of the stored name, a raster image inline, every other
file `Content-Disposition: attachment` with the name of the file, `X-Content-Type-Options:
nosniff`, `Content-Security-Policy: sandbox`, `Cache-Control: private, no-store`. A browser
client fetches it with the token (not a plain `<a href>`/`<img src>`, which sends no
token and reads only a public file) and saves or shows the blob.

## Files the server generates

`FileUpload.objects.create_for(author, name, content)` (the manager of
`FileUploadAbstract`) stores the bytes (or a text, UTF-8, or a Django `File`) under the name
and returns the file: the size limit of the uploads does not apply. `author` owns it (sees
it, links it); None keeps it without an author outside a request (inside one bazis-author
makes the user of the request its author). Link it to the object yourself and declare the
field in `files_visible`: the readers of the object read it.

```python
certificate.file = FileUpload.objects.create_for(None, f'certificate-{code}.pdf', render_pdf(certificate))
certificate.save(update_fields=['file'])
```

A PDF with reportlab needs a TTF font for any text beyond Latin-1 (the standard fonts of
PDF have no Cyrillic). Take it from a pip package, not from a local system or cache, so
that every install has the same file and its license: matplotlib ships DejaVu Sans
(`mpl-data/fonts/ttf/DejaVuSans.ttf`, `DejaVuSans-Bold.ttf`, the license
`LICENSE_DEJAVU` beside them). Add `reportlab` and `matplotlib` to the requirements of the
project (bazis-uploadable depends on neither):

```python
from io import BytesIO
from pathlib import Path

import matplotlib
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONTS = Path(matplotlib.get_data_path()) / 'fonts' / 'ttf'


def register_fonts():
    if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('DejaVuSans', str(FONTS / 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', str(FONTS / 'DejaVuSans-Bold.ttf')))


def render_pdf(certificate) -> bytes:
    register_fonts()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont('DejaVuSans-Bold', 24)
    pdf.drawString(72, 760, certificate.course.title)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
```

Generate a heavy document in a background task (bazis-bg) rather than in the request.

## Serving

A file is whatever the client sent: an HTML page or an SVG image runs its scripts when it
is opened from the media host, and if that host is the origin of the application, the
scripts read its storage (the JWT in `localStorage`).

- Serve `MEDIA_ROOT` (or the bucket) from a separate origin (`MEDIA_HOST_URL`), never from
  the origin of the frontend or the API.
- Serve only raster images inline; send every other file with `Content-Disposition:
  attachment`, and send `X-Content-Type-Options: nosniff` (and, where possible,
  `Content-Security-Policy: sandbox`). For the file system storage the web server of the
  media host does it, e.g. nginx:

  ```nginx
  map $uri $media_disposition {           # http context
      ~*\.(png|jpe?g|gif|webp|avif|bmp)$ "";
      default attachment;
  }
  location /media/ {
      add_header X-Content-Type-Options nosniff always;
      add_header Content-Security-Policy "sandbox" always;
      add_header Content-Disposition $media_disposition always;  # empty: not sent
  }
  ```

- An S3 storage of django-storages writes each object with the type of its name (not the
  type the client declared) and `Content-Disposition: attachment` unless it is a raster
  image (`S3SafeServingMixin`); `nosniff` and CSP are headers of the CDN or proxy in front
  of the bucket. Other remote storages (GCS, Azure) set `content_disposition` in their own
  `get_object_parameters`.
- The media URL of a file (the attribute `file`) is readable by anyone who has it, for as
  long as the storage serves it: the access control of the API hides the URL, not the
  file, and a user keeps the URL after he loses access to the object. For private files
  either do not serve the files publicly and read them through the download route (it
  checks the access on every request), or use a storage that signs its URLs (S3 with
  `AWS_QUERYSTRING_AUTH`, no `public-read` ACL; the URL expires). With the file system
  storage, `MEDIA_ROOT` served by the media host (or by the application in DEBUG) is
  public: keep the files whose access matters out of it (a storage with its own
  `location` outside `MEDIA_ROOT`, `BS_BAZIS_STORAGE_FILE_UPLOAD`) and use the download
  route; the attribute `file` is then no working URL for the clients.
- The FastAPI app redirects `MEDIA_URL` to `MEDIA_HOST_URL` (else to `ADMIN_HOST_URL`);
  `django.views.static.serve` of a sample `urls.py` is for development only: it sends no
  `Content-Disposition`.

## Models

- `FileUploadAbstract` (`bazis.contrib.uploadable.models_abstract`): `AuthorMixin` of
  bazis-author (`author`, `author_updated`) and the fields `file`, `name`, `extension`,
  `uploaded_anonymously` (the time a guest uploaded it, else None); its manager `objects`
  has `create_for` (above), `anonymous(tokens)` and `anonymous_expired()` (Anonymous
  uploads).
  `save()` fills `name` from the file name if it is empty, and `extension` from `name`
  (without the dot). `size` reads the size from the storage and is 0 if the file is missing.
  A model of the project that subclasses it gets the author fields and
  `uploaded_anonymously` (2.8; run `makemigrations`).
- The migrations of `FileUpload` depend on the user model (its `author`): a model of the
  project that references `FileUpload` depends on the user model too. A user model with a
  foreign key to that model (or to another model of its app) is then a migration cycle,
  `CircularDependencyError` (`users.0001_initial` → `<app>.0001_initial` →
  `uploadable.0004_fileupload_author`): put the foreign key of the user in a second
  migration of the users app (comment the field out,
  `makemigrations --skip-checks --noinput`, restore it, `makemigrations users --noinput`;
  see "A foreign key of the user to a model of the project" in the guide of bazis-users).
- Files are stored under `files/<model class name in lower case>/` with a hashed name.
- The id of `FileUpload` is an integer: the route hides the files the user does not see,
  it does not rely on unguessable ids; a guest attaches his uploads by their signed token
  (Anonymous uploads).

## Rules

- The size limit applies only to the upload action of `FileUploadRouteSet` (and its
  subclasses), not to `FileField`s of other models.
- Deleting a `FileUpload` object does not delete the file from the storage
  (`uploadable_clean_anonymous` deletes both for the expired anonymous uploads).
- Anonymous uploads: always with a size limit, a proxy body limit, the clean-up scheduled
  and `anonymous(tokens)` only for a guest (a user: his own files by id).
- A route set that serves guests and declares `files_visible` makes public the files of
  the objects its `restrict_queryset` gives a guest: restrict it (`uploadable.W003`).
