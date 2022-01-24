from io import BytesIO
from pathlib import Path

from shrinkwrap import BundleDownloader

import mock
import pytest


@pytest.fixture()
def mock_overlay_list():
    with mock.patch("shrinkwrap.OverlayDownloader.list", new_callable=mock.PropertyMock) as ol:
        ol.return_value = {"test-overlay.yaml": "file:///"}
        yield ol


@pytest.fixture()
def mock_ch_downloader():
    with mock.patch("shrinkwrap.BundleDownloader._charmhub_downloader") as dl:
        yield dl


@pytest.fixture()
def mock_cs_downloader():
    with mock.patch("shrinkwrap.BundleDownloader._charmstore_downloader") as dl:
        yield dl


@mock.patch("shrinkwrap.requests.get")
@mock.patch("shrinkwrap.requests.post")
@mock.patch("shrinkwrap.zipfile.ZipFile")
def test_charmhub_downloader(mock_zipfile, mock_post, mock_get, tmp_dir):
    args = mock.MagicMock()
    args.bundle = "ch:kubernetes-unit-test"
    args.channel = None
    args.overlay = []

    bundle_mock_url = mock.MagicMock()
    mock_post.return_value.json.return_value = {"results": [{"charm": {"download": {"url": bundle_mock_url}}}]}
    mock_downloaded = mock_zipfile.return_value.extractall.return_value
    mock_get.return_value.content = b"bytes-values"

    downloader = BundleDownloader(tmp_dir, args)
    result = downloader.bundle_download()
    assert result is mock_downloaded
    mock_post.assert_called_once_with(
        "https://api.charmhub.io/v2/charms/refresh",
        json={
            "context": [],
            "actions": [
                {
                    "name": "kubernetes-unit-test",
                    "base": {"name": "ubuntu", "architecture": "amd64", "channel": "stable"},
                    "action": "install",
                    "instance-key": "shrinkwrap",
                }
            ],
        },
    )
    mock_get.assert_called_once_with(bundle_mock_url)
    mock_zipfile.assert_called_once()
    assert isinstance(mock_zipfile.call_args.args[0], BytesIO)


@mock.patch("shrinkwrap.requests.get")
@mock.patch("shrinkwrap.zipfile.ZipFile")
def test_charmstore_downloader(mock_zipfile, mock_get, tmp_dir):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = []

    mock_downloaded = mock_zipfile.return_value.extractall.return_value
    mock_get.return_value.content = b"bytes-values"

    downloader = BundleDownloader(tmp_dir, args)
    result = downloader.bundle_download()
    assert result is mock_downloaded
    mock_get.assert_called_once_with("https://api.jujucharms.com/charmstore/v5/kubernetes-unit-test/archive")
    mock_zipfile.assert_called_once()
    assert isinstance(mock_zipfile.call_args.args[0], BytesIO)


def test_bundle_downloader(tmp_dir, mock_ch_downloader, mock_cs_downloader):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = []
    charms_path = Path(tmp_dir) / "charms"

    downloader = BundleDownloader(tmp_dir, args)
    assert downloader.bundle_path == charms_path / ".bundle"

    assert downloader.app_download("etcd", {"charm": "etcd", "channel": "latest/edge"}) == "etcd"
    assert (
        downloader.app_download("containerd", {"charm": "cs:~containers/containerd-160"})
        == "cs:~containers/containerd-160"
    )
    mock_ch_downloader.assert_called_once_with("etcd", charms_path / "etcd", channel="latest/edge")
    mock_cs_downloader.assert_called_once_with("~containers/containerd-160", charms_path / "containerd")

    mock_ch_downloader.reset_mock()
    mock_cs_downloader.reset_mock()
    downloader.bundle_download()
    mock_ch_downloader.assert_not_called()
    mock_cs_downloader.assert_called_once_with("kubernetes-unit-test", downloader.bundle_path)


def test_bundle_downloader_properties(tmp_dir, mock_overlay_list):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = ["test-overlay.yaml"]
    downloader = BundleDownloader(tmp_dir, args)

    # mock downloaded already
    with (Path(__file__).parent / "test_bundle.yaml").open() as fp:
        (downloader.bundle_path / "bundle.yaml").write_text(fp.read())
    with (Path(__file__).parent / "test_overlay.yaml").open() as fp:
        (downloader.bundle_path / "test-overlay.yaml").write_text(fp.read())

    assert downloader.bundles["bundle.yaml"]["applications"].keys() == {
        "containerd",
        "easyrsa",
        "etcd",
        "flannel",
        "kubernetes-control-plane",
        "kubernetes-worker",
    }
    assert downloader.bundles["test-overlay.yaml"]["applications"].keys() == {
        "calico",
        "flannel",
        "openstack-integrator",
    }
    assert downloader.applications.keys() == {
        "calico",
        "containerd",
        "easyrsa",
        "etcd",
        "flannel",
        "kubernetes-control-plane",
        "kubernetes-worker",
        "openstack-integrator",
    }
