# bazis-uploadable — guide for AI agents

File uploads for Bazis: the model `uploadable.FileUpload` (a file in a Django storage with
its name, extension and author) and a JSON:API route that accepts the file as multipart form
data. Other models can reference uploaded files with a foreign key to `uploadable.FileUpload`.
Needs bazis-users and bazis-author: a file has an `author`, the user who uploaded it.

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
- Routes: `bazis.contrib.uploadable.router` registers `FileUploadRouteSet`.

## Access

`FileUploadRouteSet` (`AuthorRequiredRouteBase` of bazis-author) requires a user (401
without a token):

- create: the user uploads a file and becomes its `author` (a client cannot set it);
- list (`/`, `/_id/`), retrieve and download (`/{id}/download/`): the files whose `author`
  is the user and the files of the objects he sees through a route set that declares them
  in `files_visible` (below); another file is 404;
- no update, no delete (405) and no relationships endpoints: a file referenced by the
  objects of other users stays as it was.

`FileUploadRouteSet` is the default route of `uploadable.FileUpload`: its classmethod
`restrict_queryset` (none for an anonymous user, the authenticated user of the request
`UserMixin.CTX_USER_REQUEST` when the caller passes no user) is also what the other
routes link and include (the core, Bazis 2.7). `CTX_USER_REQUEST` is set by the routes of
bazis-users (`UserRouteBase`) and its Django middleware: a route without a user (a plain
`JsonapiRouteBase`) does not set it, so there a logged-in user is anonymous for the files,
cannot link even his own files (403) and does not see them in `included`.

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
  `included` of the other routes. An anonymous user sees no file.
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
        user = user or UserMixin.CTX_USER_REQUEST.get()
        own = super().restrict_queryset(qs, access_action, user=user, **kwargs)
        if user is None or user.is_anonymous or kwargs.get('link'):
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
  `file` (its URL in the storage), `name`, `extension` and `size` (bytes).

## Download

`GET <prefix>/uploadable/file_upload/{id}/download/` (a user, the bearer token) streams the
content of a file the user sees (his own and the visible ones, as the item): 401 without a
user, 404 for another file or a file missing from the storage. It is served as the media
host should serve it: the type of the stored name, a raster image inline, every other
file `Content-Disposition: attachment` with the name of the file, `X-Content-Type-Options:
nosniff`, `Content-Security-Policy: sandbox`, `Cache-Control: private, no-store`. A browser
client fetches it with the token (not a plain `<a href>`/`<img src>`, which sends no
token) and saves or shows the blob.

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
  bazis-author (`author`, `author_updated`) and the fields `file`, `name`, `extension`;
  its manager `objects` has `create_for` (above).
  `save()` fills `name` from the file name if it is empty, and `extension` from `name`
  (without the dot). `size` reads the size from the storage and is 0 if the file is missing.
  A model of the project that subclasses it gets the author fields (run `makemigrations`).
- Files are stored under `files/<model class name in lower case>/` with a hashed name.
- The id of `FileUpload` is an integer: the route hides the files the user does not see,
  it does not rely on unguessable ids.

## Rules

- The size limit applies only to the upload action of `FileUploadRouteSet` (and its
  subclasses), not to `FileField`s of other models.
- Deleting a `FileUpload` object does not delete the file from the storage.
