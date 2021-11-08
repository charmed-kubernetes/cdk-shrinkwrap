from pathlib import Path

from shrinkwrap import ResourceDownloader

import mock
import pytest


@pytest.fixture()
def mock_requests():
    with mock.patch("shrinkwrap.requests.get") as mr:
        yield mr


@pytest.fixture()
def mock_wget_cmd():
    with mock.patch("shrinkwrap.check_call") as cc:
        yield cc


def test_resource_downloader(tmp_dir, mock_requests, mock_wget_cmd):
    downloader = ResourceDownloader(tmp_dir)
    assert downloader.path.exists(), "Resource path doesn't exist"

    with pytest.raises(NotImplementedError) as ie:
        downloader.list("etcd", "latest/stable")
    assert str(ie.value) == "Fetching of resources from Charmhub not supported."

    assert downloader.list("cs:etcd", "latest/stable") == mock_requests.return_value.json.return_value
    mock_requests.assert_called_once_with(
        "https://api.jujucharms.com/charmstore/v5/etcd/meta/resources",
        params={"channel": "latest/stable"},
    )

    target = downloader.mark_download("etcd", "cs:etcd", "snapshot", 0, "snapshot.tar.gz")
    assert target == Path(tmp_dir) / "resources" / "etcd" / "snapshot" / "snapshot.tar.gz"
    assert not target.parent.exists()

    downloader.download()
    assert target.parent.exists(), "Target path not created"
