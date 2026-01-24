# Bazis Uploadable

[![PyPI version](https://img.shields.io/pypi/v/bazis-uploadable.svg)](https://pypi.org/project/bazis-uploadable/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bazis-uploadable.svg)](https://pypi.org/project/bazis-uploadable/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

An extension package for Bazis, providing a ready-to-use solution for file uploading and management with support for various storage backends.

## Quick Start

```bash
# Install the package
uv add bazis-uploadable

# Create a model for file uploads
from bazis.contrib.uploadable.models_abstract import FileUploadAbstract
from bazis.core.models_abstract import DtMixin, UuidMixin

class Document(FileUploadAbstract, DtMixin, UuidMixin):
    """Uploadable document"""

    class Meta:
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'

# Create a route for uploads
from bazis.contrib.uploadable.routes_abstract import FileUploadRouteSet
from django.apps import apps

class DocumentRouteSet(FileUploadRouteSet):
    model = apps.get_model('myapp.Document')
```

## Table of Contents

- [Description](#description)
- [Requirements](#requirements)
- [Installation](#installation)
- [Core Components](#core-components)
  - [FileUploadAbstract](#fileuploadabstract)
  - [FileUploadRouteSet](#fileuploadrouteset)
  - [Storage Configuration](#storage-configuration)
- [Usage](#usage)
  - [Creating a File Model](#creating-a-file-model)
  - [Creating an Upload Route](#creating-an-upload-route)
  - [Uploading Files via API](#uploading-files-via-api)
- [Storage Configuration](#storage-configuration)
- [Examples](#examples)
- [License](#license)
- [Links](#links)

## Description

**Bazis Uploadable** is an extension package for the Bazis framework that provides a ready-to-use solution for file uploading and management. The package includes:

- **FileUploadAbstract** — abstract model with fields for storing files and metadata
- **FileUploadRouteSet** — ready-to-use route with multipart/form-data upload support
- **Flexible storage configuration** — support for local storage, S3, and other backends
- **Automatic metadata extraction** — filename, extension, size
- **JSON:API integration** — standardized response format

**This package requires the base `bazis` package to be installed.**

## Requirements

- **Python**: 3.12+
- **bazis**: latest version
- **PostgreSQL**: 12+
- **Redis**: For caching

## Installation

### Using uv (recommended)

```bash
uv add bazis-uploadable
```

### Using pip

```bash
pip install bazis-uploadable
```

## Core Components

### FileUploadAbstract

Abstract model for storing uploaded files.

**Location**: `bazis.contrib.uploadable.models_abstract.FileUploadAbstract`

**Fields**:

- `file` — FileField for storing the file
- `name` — filename (optional, automatically filled from file name)
- `extension` — file extension (optional, automatically extracted)

**Properties**:

- `size` — file size in bytes (cached_property)

**Features**:

- Automatically extracts filename and extension on save
- Uses `get_file_path` to generate storage path
- Supports custom storage backends via settings
- Returns 0 for `size` when file is absent instead of raising an error

**Usage example**:

```python
from bazis.contrib.uploadable.models_abstract import FileUploadAbstract
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin

class Document(FileUploadAbstract, DtMixin, UuidMixin):
    """Document with additional fields"""
    description = models.TextField('Description', blank=True, null=True)

    class Meta:
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'
```

### FileUploadRouteSet

Ready-to-use route for file uploading via multipart/form-data.

**Location**: `bazis.contrib.uploadable.routes_abstract.FileUploadRouteSet`

**Features**:

- Accepts files via `multipart/form-data`
- Automatically includes `size` and `extension` fields in schema
- Supports optional `name` field for renaming files
- Returns data in JSON:API format

**Endpoint**:

- **POST /** — upload a new file

**Usage example**:

```python
from bazis.contrib.uploadable.routes_abstract import FileUploadRouteSet
from django.apps import apps

class DocumentRouteSet(FileUploadRouteSet):
    model = apps.get_model('myapp.Document')
```

### Storage Configuration

By default, Django's standard `FileSystemStorage` is used. You can configure custom storage via settings.

**settings.py**:

```python
# Local storage (default)
BAZIS_STORAGE_FILE_UPLOAD = None  # or 'django.core.files.storage.FileSystemStorage'

# S3-compatible storage
BAZIS_STORAGE_FILE_UPLOAD = 'storages.backends.s3boto3.S3Boto3Storage'

# Other storage backends
BAZIS_STORAGE_FILE_UPLOAD = 'path.to.your.CustomStorage'
```

## Usage

### Creating a File Model

```python
from bazis.contrib.uploadable.models_abstract import FileUploadAbstract
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin
from django.db import models

class Document(FileUploadAbstract, DtMixin, UuidMixin):
    """Document with metadata"""
    description = models.TextField('Description', blank=True, null=True)
    category = models.CharField('Category', max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'

    def __str__(self):
        return self.name or self.file.name
```

### Creating an Upload Route

**routes.py**:

```python
from bazis.contrib.uploadable.routes_abstract import FileUploadRouteSet
from bazis.core.schemas.fields import SchemaField, SchemaFields
from django.apps import apps

class DocumentRouteSet(FileUploadRouteSet):
    model = apps.get_model('myapp.Document')

    # Adding additional fields to schema
    fields = {
        None: SchemaFields(
            include={
                'description': None,
                'category': None,
            },
        ),
    }
```

**router.py**:

```python
from bazis.core.routing import BazisRouter
from . import routes

router = BazisRouter(tags=['Documents'])
router.register(routes.DocumentRouteSet.as_router())
```

### Uploading Files via API

#### Uploading a file with automatic name

```bash
POST /api/v1/documents/document/
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="file"; filename="report.pdf"
Content-Type: application/pdf

[binary data]
--boundary--
```

**Response**:
```json
{
  "data": {
    "type": "myapp.document",
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "attributes": {
      "name": "report.pdf",
      "extension": "pdf",
      "size": 102400,
      "dt_created": "2024-01-15T10:30:00Z"
    },
    "relationships": {
      "file": {
        "data": {
          "url": "/media/uploads/2024/01/15/report.pdf"
        }
      }
    }
  }
}
```

#### Uploading a file with custom name

```bash
POST /api/v1/documents/document/
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="file"; filename="original.pdf"
Content-Type: application/pdf

[binary data]
--boundary
Content-Disposition: form-data; name="name"

Monthly Report January 2024.pdf
--boundary--
```

**Response**:
```json
{
  "data": {
    "type": "myapp.document",
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "attributes": {
      "name": "Monthly Report January 2024.pdf",
      "extension": "pdf",
      "size": 102400
    }
  }
}
```

#### Uploading with additional fields

```bash
POST /api/v1/documents/document/
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="file"; filename="invoice.pdf"

[binary data]
--boundary
Content-Disposition: form-data; name="name"

Invoice #12345
--boundary
Content-Disposition: form-data; name="description"

Invoice for January 2024 services
--boundary
Content-Disposition: form-data; name="category"

Finance
--boundary--
```

## Storage Configuration

### Local Storage (default)

```python
# settings.py
MEDIA_ROOT = '/var/www/media/'
MEDIA_URL = '/media/'

# FileSystemStorage is used by default
BAZIS_STORAGE_FILE_UPLOAD = None
```

### Amazon S3

```bash
# Install dependencies
uv add django-storages boto3
```

```python
# settings.py
BAZIS_STORAGE_FILE_UPLOAD = 'storages.backends.s3boto3.S3Boto3Storage'

# S3 configuration
AWS_ACCESS_KEY_ID = 'your-access-key'
AWS_SECRET_ACCESS_KEY = 'your-secret-key'
AWS_STORAGE_BUCKET_NAME = 'your-bucket-name'
AWS_S3_REGION_NAME = 'us-east-1'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
AWS_DEFAULT_ACL = 'public-read'
```

### MinIO (S3-compatible storage)

```python
# settings.py
BAZIS_STORAGE_FILE_UPLOAD = 'storages.backends.s3boto3.S3Boto3Storage'

AWS_ACCESS_KEY_ID = 'minio-access-key'
AWS_SECRET_ACCESS_KEY = 'minio-secret-key'
AWS_STORAGE_BUCKET_NAME = 'uploads'
AWS_S3_ENDPOINT_URL = 'http://minio:9000'
AWS_S3_USE_SSL = False
AWS_DEFAULT_ACL = 'public-read'
```

### Google Cloud Storage

```bash
# Install dependencies
uv add django-storages google-cloud-storage
```

```python
# settings.py
BAZIS_STORAGE_FILE_UPLOAD = 'storages.backends.gcloud.GoogleCloudStorage'

GS_BUCKET_NAME = 'your-bucket-name'
GS_PROJECT_ID = 'your-project-id'
GS_CREDENTIALS = service_account.Credentials.from_service_account_file(
    'path/to/service-account.json'
)
```

### Custom Storage

You can create your own storage by inheriting from Django Storage:

```python
# myapp/storage.py
from django.core.files.storage import FileSystemStorage

class CustomStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(
            location='/custom/path/',
            base_url='/custom/'
        )

    def _save(self, name, content):
        # Custom save logic
        return super()._save(name, content)
```

```python
# settings.py
BAZIS_STORAGE_FILE_UPLOAD = 'myapp.storage.CustomStorage'
```

## Examples

### Complete document application example

**models.py**:

```python
from bazis.contrib.uploadable.models_abstract import FileUploadAbstract
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin
from django.db import models

class DocumentCategory(models.TextChoices):
    INVOICE = 'invoice', 'Invoice'
    CONTRACT = 'contract', 'Contract'
    REPORT = 'report', 'Report'
    OTHER = 'other', 'Other'

class Document(FileUploadAbstract, DtMixin, UuidMixin):
    """Document with category and description"""
    description = models.TextField('Description', blank=True, null=True)
    category = models.CharField(
        'Category',
        max_length=20,
        choices=DocumentCategory.choices,
        default=DocumentCategory.OTHER
    )

    class Meta:
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'

    def __str__(self):
        return f'{self.get_category_display()}: {self.name}'
```

**routes.py**:

```python
from bazis.contrib.uploadable.routes_abstract import FileUploadRouteSet
from bazis.core.schemas.fields import SchemaFields
from django.apps import apps

class DocumentRouteSet(FileUploadRouteSet):
    model = apps.get_model('myapp.Document')

    fields = {
        None: SchemaFields(
            include={
                'description': None,
                'category': None,
            },
        ),
    }
```

**router.py**:

```python
from bazis.core.routing import BazisRouter
from . import routes

router = BazisRouter(tags=['Documents'])
router.register(routes.DocumentRouteSet.as_router())
```

**admin.py**:

```python
from django.contrib import admin
from bazis.core.admin_abstract import DtAdminMixin
from .models import Document

@admin.register(Document)
class DocumentAdmin(DtAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'extension', 'size_display', 'dt_created')
    list_filter = ('category', 'extension')
    search_fields = ('name', 'description')
    readonly_fields = ('extension', 'size', 'dt_created', 'dt_updated')

    def size_display(self, obj):
        """Human-readable file size"""
        size = obj.size
        if size < 1024:
            return f'{size} B'
        elif size < 1024 * 1024:
            return f'{size / 1024:.2f} KB'
        else:
            return f'{size / (1024 * 1024):.2f} MB'
    size_display.short_description = 'Size'
```

### Client application usage example

**JavaScript (file upload)**:

```javascript
async function uploadDocument(file, category, description) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('category', category);

  if (description) {
    formData.append('description', description);
  }

  const response = await fetch('/api/v1/documents/document/', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  });

  if (!response.ok) {
    throw new Error('Upload failed');
  }

  return await response.json();
}

// Usage
const fileInput = document.getElementById('fileInput');
const file = fileInput.files[0];

try {
  const result = await uploadDocument(file, 'invoice', 'Monthly invoice');
  console.log('Uploaded:', result.data.id);
  console.log('File URL:', result.data.attributes.file);
} catch (error) {
  console.error('Error:', error);
}
```

**Python (file upload via requests)**:

```python
import requests

def upload_document(file_path, category, description=None):
    url = 'http://api.example.com/api/v1/documents/document/'

    with open(file_path, 'rb') as file:
        files = {'file': file}
        data = {
            'category': category,
        }

        if description:
            data['description'] = description

        headers = {
            'Authorization': f'Bearer {token}'
        }

        response = requests.post(url, files=files, data=data, headers=headers)
        response.raise_for_status()

        return response.json()

# Usage
result = upload_document(
    '/path/to/invoice.pdf',
    category='invoice',
    description='Monthly invoice for January'
)

print(f"Uploaded: {result['data']['id']}")
print(f"Size: {result['data']['attributes']['size']} bytes")
```

### Getting list of files

```bash
GET /api/v1/documents/document/
Authorization: Bearer <token>
```

**Response**:
```json
{
  "data": [
    {
      "type": "myapp.document",
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "attributes": {
        "name": "invoice.pdf",
        "extension": "pdf",
        "size": 102400,
        "category": "invoice",
        "description": "Monthly invoice",
        "dt_created": "2024-01-15T10:30:00Z"
      }
    },
    {
      "type": "myapp.document",
      "id": "987e6543-e21b-32d1-b654-426614174001",
      "attributes": {
        "name": "report.docx",
        "extension": "docx",
        "size": 256000,
        "category": "report",
        "dt_created": "2024-01-16T14:20:00Z"
      }
    }
  ],
  "meta": {
    "count": 2
  }
}
```

### Filtering by extension

```bash
GET /api/v1/documents/document/?filter[extension]=pdf
```

### Filtering by category

```bash
GET /api/v1/documents/document/?filter[category]=invoice
```

## License

Apache License 2.0

See [LICENSE](LICENSE) file for details.

## Links

- [Bazis Documentation](https://github.com/ecofuture-tech/bazis) — main repository
- [Bazis Uploadable Repository](https://github.com/ecofuture-tech/bazis-uploadable) — package repository
- [Issue Tracker](https://github.com/ecofuture-tech/bazis-uploadable/issues) — report bugs or request features
- [Django Storages](https://django-storages.readthedocs.io/) — storage backend documentation

## Support

If you have questions or issues:
- Check the [Bazis documentation](https://github.com/ecofuture-tech/bazis)
- Search through [existing issues](https://github.com/ecofuture-tech/bazis-uploadable/issues)
- Create a [new issue](https://github.com/ecofuture-tech/bazis-uploadable/issues/new) with detailed information

---

Made with ❤️ by Bazis team