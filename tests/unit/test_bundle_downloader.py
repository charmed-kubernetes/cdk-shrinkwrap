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
@mock.patch("shrinkwrap.zipfile.ZipFile")
def test_charmhub_downloader(mock_zipfile, mock_get, tmpdir):
    args = mock.MagicMock()
    args.bundle = "ch:kubernetes-unit-test"
    args.channel = None
    args.overlay = []

    def mock_get_response(url, **_kwargs):
        response = mock.MagicMock()
        if "info" in url:
            response.json.return_value = {"default-release": {"revision": {"download": {"url": bundle_mock_url}}}}
        elif bundle_mock_url == url:
            response.content = b"bytes-values"
        return response

    bundle_mock_url = mock.MagicMock()
    mock_get.side_effect = mock_get_response

    downloader = BundleDownloader(tmpdir, args)
    result = downloader.bundle_download()
    assert result == tmpdir / "charms" / ".bundle" / "bundle.yaml"
    expected_gets = [
        mock.call(
            "https://api.charmhub.io/v2/charms/info/kubernetes-unit-test",
            params=dict(channel=args.channel, fields="default-release.revision.download.url"),
        ),
        mock.call(bundle_mock_url),
    ]
    mock_get.assert_has_calls(expected_gets)
    mock_zipfile.assert_called_once()
    assert isinstance(mock_zipfile.call_args.args[0], BytesIO)


@mock.patch("shrinkwrap.requests.get")
@mock.patch("shrinkwrap.zipfile.ZipFile")
def test_charmstore_downloader(mock_zipfile, mock_get, tmpdir):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = []

    mock_get.return_value.content = b"bytes-values"

    downloader = BundleDownloader(tmpdir, args)
    result = downloader.bundle_download()
    assert result == tmpdir / "charms" / ".bundle" / "bundle.yaml"
    mock_get.assert_called_once_with(
        "https://api.jujucharms.com/charmstore/v5/kubernetes-unit-test/archive", params={"channel": args.channel}
    )
    mock_zipfile.assert_called_once()
    assert isinstance(mock_zipfile.call_args.args[0], BytesIO)


def test_bundle_downloader(tmpdir, mock_ch_downloader, mock_cs_downloader):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = []
    charms_path = Path(tmpdir) / "charms"
    etcd_path = charms_path / "etcd" / "latest" / "edge"
    containerd_path = charms_path / "containerd"

    downloader = BundleDownloader(tmpdir, args)
    assert downloader.bundle_path == charms_path / ".bundle"

    assert downloader.app_download("etcd", {"charm": "etcd", "channel": "latest/edge"}) == ("etcd", etcd_path)
    assert downloader.app_download("containerd", {"charm": "cs:~containers/containerd-160"}) == (
        "cs:~containers/containerd-160",
        containerd_path,
    )
    mock_ch_downloader.assert_called_once_with("etcd", etcd_path, channel="latest/edge")
    mock_cs_downloader.assert_called_once_with("~containers/containerd-160", containerd_path, channel=None)

    mock_ch_downloader.reset_mock()
    mock_cs_downloader.reset_mock()
    downloader.bundle_download()
    mock_ch_downloader.assert_not_called()
    mock_cs_downloader.assert_called_once_with("kubernetes-unit-test", downloader.bundle_path, channel=args.channel)


def test_bundle_downloader_properties(tmpdir, test_bundle, test_overlay, mock_overlay_list):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = ["test-overlay.yaml"]
    downloader = BundleDownloader(tmpdir, args)

    # mock downloaded already
    with test_bundle.file.open() as fp:
        (downloader.bundle_path / "bundle.yaml").write_text(fp.read())
    with test_overlay.open() as fp:
        (downloader.bundle_path / "test-overlay.yaml").write_text(fp.read())

    assert downloader.bundles["bundle.yaml"][test_bundle.apps].keys() == {
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
