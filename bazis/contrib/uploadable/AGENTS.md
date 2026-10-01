# bazis-uploadable — guide for AI agents

File uploads for Bazis: the model `uploadable.FileUpload` (a file in a Django storage with
its name and extension) and a JSON:API route that accepts the file as multipart form data.
Other models can reference uploaded files with a foreign key to `uploadable.FileUpload`.

## Setup

- `BS_INSTALLED_APPS` includes `bazis.contrib.uploadable` (the model and its migrations:
  run `migrate`). If `BS_BAZIS_APPS` is set, list it there too.
- Storage: `BS_BAZIS_STORAGE_FILE_UPLOAD` is the dotted path of a Django storage class,
  created without arguments (e.g. an S3 storage configured by its own settings). Empty
  (default): `FileSystemStorage` in `MEDIA_ROOT` (`BS_MEDIA_ROOT`). The class is imported
  once, when the models are loaded; the field uses a callable storage, so changing the
  setting needs no migration.
- `BS_BAZIS_FILE_UPLOAD_MAX_SIZE`: the maximum file size in bytes, `0` (default) = no
  limit. A larger file is rejected with 413 and the error code `ERR_FILE_TOO_LARGE`. The
  check runs after the whole request body is received: also limit the request body size
  on the reverse proxy.
- Routes: `bazis.contrib.uploadable.router` registers `FileUploadRouteSet`, which has no
  access control: anyone who reaches the API can upload, list, change and delete files
  (`uploadable.W001`). In production register a subclass of `FileUploadRouteSet` that
  requires a user (`UserRequiredRouteBase` of bazis-users) or permissions (bazis-permit)
  with `router.register(MyFileRouteSet.as_router())`. List `FileUploadRouteSet` first
  among the bases: its `action_create` reads the multipart form.

## Upload

`POST <prefix>/uploadable/file_upload/` (the bundled router) with `multipart/form-data`:

- `file` (required): the file; `name` (optional): the file name, by default the file name
  of the uploaded file; `id` (optional).
- Response 201: a JSON:API item of type `uploadable.file_upload` with the attributes
  `file`, `name`, `extension` and `size` (bytes).
- List, retrieve, update and delete are the usual JSON:API actions of the route.

## Models

- `FileUploadAbstract` (`bazis.contrib.uploadable.models_abstract`): the fields `file`,
  `name`, `extension`. `save()` fills `name` from the file name if it is empty, and
  `extension` from `name` (without the dot). `size` reads the size from the storage and is
  0 if the file is missing.
- Files are stored under `files/<model class name in lower case>/` with a hashed name.

## Rules

- The size limit applies only to the upload action of `FileUploadRouteSet` (and its
  subclasses), not to `FileField`s of other models.
- Deleting a `FileUpload` object does not delete the file from the storage.
