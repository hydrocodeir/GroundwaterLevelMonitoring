"""Prevent mixed HTML/JS releases in a long-running local dashboard process."""
import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app, current_asset_version


def test_template_version_is_evaluated_each_request_without_server_restart():
    with TestClient(app) as client:
        with patch('app.main.current_asset_version',return_value='release-first'):
            first=client.get('/aquifer-3d')
        with patch('app.main.current_asset_version',return_value='release-second'):
            second=client.get('/aquifer-3d')
    assert first.status_code==second.status_code==200
    assert 'aquifer3d-bootstrap.js?v=release-first' in first.text
    assert 'aquifer3d-bootstrap.js?v=release-second' in second.text
    assert 'release-first' not in second.text
    assert first.headers['cache-control']==second.headers['cache-control']=='no-cache'


def test_version_changes_when_non_latest_file_changes(tmp_path):
    import os
    files=['frontend/assets/js/first.js','frontend/assets/js/second.js',
           'frontend/templates/aquifer3d.html','frontend/assets/data/khorasan-razavi-urban.geojson',
           'app/data_service.py','scripts/waterq_compute.py']
    for name in files:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('test')
    first=tmp_path/files[0];second=tmp_path/files[1]
    os.utime(first,ns=(100,100));os.utime(second,ns=(1000,1000))
    with patch('app.main.ROOT',tmp_path):
        before=current_asset_version()
        assert before==current_asset_version()
        os.utime(first,ns=(200,200))  # Still below the previous maximum.
        assert current_asset_version()!=before


def test_mutable_modules_revalidate_but_runtime_wheels_keep_caching():
    with TestClient(app) as client:
        for name in ['/assets/js/aquifer3d.js','/assets/js/aquifer3d-bootstrap.js',
                     '/assets/css/aquifer3d.css','/comparison','/aquifer3d-sw.js']:
            response=client.get(name)
            assert response.status_code==200
            assert response.headers['cache-control']=='no-cache'
        wheel=next((Path(__file__).resolve().parents[1]/'frontend/assets/pyodide/packages').glob('numpy*.whl'))
        assert 'cache-control' not in client.head('/assets/pyodide/packages/'+wheel.name).headers
