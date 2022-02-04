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


def test_resource_downloader(tmpdir, mock_requests, mock_wget_cmd):
    downloader = ResourceDownloader(tmpdir)
    assert downloader.path.exists(), "Resource path doesn't exist"

    # Fetch from Charmhub
    CH_URL = "https://api.charmhub.io/api/v1/resources/download"
    mock_requests.return_value.json.return_value = {
        "default-release": {
            "resources": [
                {
                    "download": {"url": f"{CH_URL}/charm_8bULztKLC5fEw4Mc9gIeerQWey1pHICv.snapshot_0"},
                    "filename": "snapshot.tar.gz",
                    "name": "snapshot",
                    "revision": 0,
                    "type": "file",
                }
            ]
        }
    }
    assert downloader.list("etcd", "latest/stable") == [
        (
            "snapshot",
            "file",
            "snapshot.tar.gz",
            0,
            f"{CH_URL}/charm_8bULztKLC5fEw4Mc9gIeerQWey1pHICv.snapshot_{{revision}}",
        )
    ]

    # Fetch from Charmstore
    mock_requests.reset_mock()
    mock_requests.return_value.json.return_value = [
        {
            "Name": "snapshot",
            "Type": "file",
            "Path": "snapshot.tar.gz",
            "Description": "Tarball snapshot of an etcd clusters data.",
            "Revision": 0,
            "Size": 124,
        },
    ]
    resources = downloader.list("cs:etcd", "stable")
    assert resources == [
        (
            "snapshot",
            "file",
            "snapshot.tar.gz",
            0,
            "https://api.jujucharms.com/charmstore/v5/etcd/resource/snapshot/{revision}",
        )
    ]
    mock_requests.assert_called_once_with(
        "https://api.jujucharms.com/charmstore/v5/etcd/meta/resources",
        params={"channel": "stable"},
    )

    target = downloader.mark_download("etcd", "cs:etcd", resources[0])
    assert target == Path(tmpdir) / "resources" / "etcd" / "snapshot" / "snapshot.tar.gz"
    assert not target.parent.exists()

    downloader.download()
    assert target.parent.exists(), "Target path not created"
    mock_wget_cmd.assert_called_once_with(
        ["wget", "--quiet", "https://api.jujucharms.com/charmstore/v5/etcd/resource/snapshot/0", "-O", str(target)]
    )
