import logging

from django.apps import apps
from django.test import override_settings

import httpx
import pytest
from bazis_test_utils.utils import get_api_client

from .factories import FileUploadFactory


# Enable logging for httpx
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("httpx")


def log_request(request: httpx.Request):
    logger.debug(f"Request method: {request.method}")
    logger.debug(f"Request url: {request.url}")
    logger.debug(f"Request headers: {request.headers}")
    logger.debug(f"Request content: {request.content}")


def log_response(response: httpx.Response):
    logger.debug(f"Response status code: {response.status_code}")
    logger.debug(f"Response headers: {response.headers}")
    logger.debug(f"Response content: {response.content}")


@override_settings(MEDIA_ROOT='/tmp')
@pytest.mark.django_db(transaction=True)
def test_uploadable(sample_app, temp_file):
    with open(temp_file, 'rb') as file:
        response = get_api_client(sample_app).post(
            '/api/v1/uploadable/file_upload/',
            data={
                'name': 'Test_name.txt',
            },
            files={'file': file.read()},
            headers={
                'Content-Type': 'multipart/form-data'
            },
        )

    assert response.status_code == 201
    assert 'data' in response.json()
    assert response.json()['data']['type'] == 'uploadable.file_upload'

    file_instance = apps.get_model('uploadable.FileUpload').objects.get(
        pk=response.json()['data']['id']
    )
    assert file_instance.extension == 'txt'

    FileUploadFactory.create_batch(2)

    response = get_api_client(sample_app).get('/api/v1/uploadable/file_upload/')

    assert response.status_code == 200
    assert 'data' in response.json()
    assert all(x['type'] == 'uploadable.file_upload' for x in response.json()['data'])
