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
- list (`/`, `/_id/`) and retrieve: only the files whose `author` is the user; the file of
  another user is 404;
- no update, no delete (405) and no relationships endpoints: a file referenced by the
  objects of other users stays as it was.

Files that other users uploaded (an attachment of a shared object) are not readable
through `FileUploadRouteSet`. A client reads them through the object that references them
(`GET <object>/{id}/?include=<field>`) or through a subclass that widens `get_queryset`.
Neither is safe by itself: **the core does not yet check that a relationship targets an
object the user may see**, so a user who sets `relationships.<field> = {"id": <file id>}`
on his own object links a file of another user by its id and reads it through `include`.
Until the core version with these checks, every route set of a model that references
uploaded files verifies the files a user links: on create, on update when the file
changes, and on the relationships endpoints (or excludes them), e.g. (the sample route
set `notes.routes.NoteRouteSet`, tested in `tests/test_uploadable.py`):

```python
class NoteRouteSet(UserRequiredRouteBase):
    def check_attachment(self, file_id):  # 403 unless the user uploaded the file
        if file_id is not None and not FileUpload.objects.filter(
            pk=file_id, author=self.inject.user
        ).exists():
            raise JsonApiBazisException(JsonApiBazisError(..., status=403), status=403)

    def hook_before_create(self, item):
        self.check_attachment(item.attachment_id)
        super().hook_before_create(item)
    # hook_before_update keeps item.attachment_id, hook_after_update checks a new one;
    # hook_before_relationships_change checks the id of `attachment`
```

A subclass of `FileUploadRouteSet` that lets a client read files by their ids widens
`get_queryset` only with the files of objects the user may read, and only once linking is
checked as above. This example moves to `restrict_queryset` once the core supports it:

```python
class FileRouteSet(FileUploadRouteSet):
    def get_queryset(self):
        tasks = Task.objects.filter(...)  # the tasks the user may read
        return self.model.objects.filter(
            Q(author=self.inject.user) | Q(pk__in=tasks.values('attachment'))
        )
```

The package does not depend on bazis-permit. With it, a project subclasses
`FileUploadAbstract` with `PermitModelMixin` for its own model of files and registers a
subclass of `FileUploadRouteSet` that also inherits `PermitRouteBase`: the permissions
narrow the files of the author further; to let them decide alone, the subclass overrides
`get_queryset` without the author filter. List `FileUploadRouteSet` first among the bases:
its `action_create` reads the multipart form. Keep custom file routes as restrictive.
Files without an `author` (uploaded before 2.5, in the admin or by scripts) are visible to
no one through `FileUploadRouteSet`.

## Upload

`POST <prefix>/uploadable/file_upload/` (the bundled router) with `multipart/form-data`:

- `file` (required): the file; `name` (optional): the file name, by default the file name
  of the uploaded file. The id is generated by the server (an `id` field is ignored).
- Response 201: a JSON:API item of type `uploadable.file_upload` with the attributes
  `file` (its URL in the storage), `name`, `extension` and `size` (bytes).

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
- The media URL of a file is readable by anyone who has it: the access control of the API
  hides the URL, not the file. For private files use a storage that signs its URLs (S3
  with `AWS_QUERYSTRING_AUTH`, no `public-read` ACL).
- The FastAPI app redirects `MEDIA_URL` to `MEDIA_HOST_URL` (else to `ADMIN_HOST_URL`);
  `django.views.static.serve` of a sample `urls.py` is for development only: it sends no
  `Content-Disposition`.

## Models

- `FileUploadAbstract` (`bazis.contrib.uploadable.models_abstract`): `AuthorMixin` of
  bazis-author (`author`, `author_updated`) and the fields `file`, `name`, `extension`.
  `save()` fills `name` from the file name if it is empty, and `extension` from `name`
  (without the dot). `size` reads the size from the storage and is 0 if the file is missing.
  A model of the project that subclasses it gets the author fields (run `makemigrations`).
- Files are stored under `files/<model class name in lower case>/` with a hashed name.
- The id of `FileUpload` is an integer: the route hides the files of other users, it does
  not rely on unguessable ids.

## Rules

- The size limit applies only to the upload action of `FileUploadRouteSet` (and its
  subclasses), not to `FileField`s of other models.
- Deleting a `FileUpload` object does not delete the file from the storage.
