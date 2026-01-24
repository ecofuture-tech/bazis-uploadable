import factory

from bazis.contrib.uploadable.models import FileUpload


class FileUploadFactory(factory.django.DjangoModelFactory):
    name = factory.Faker('file_name')
    extension = factory.Faker('file_extension')
    file = factory.django.FileField()

    class Meta:
        model = FileUpload
