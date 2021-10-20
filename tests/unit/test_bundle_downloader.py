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


def test_bundle_downloader(tmp_dir, mock_ch_downloader, mock_cs_downloader):
    args = mock.MagicMock()
    args.bundle = "cs:kubernetes-unit-test"
    args.overlay = []
    downloader = BundleDownloader(tmp_dir, args)
    assert downloader.bundle_path == Path(tmp_dir) / "charms" / ".bundle"

    downloader.app_download("etcd", {"charm": "etcd", "channel": "latest/edge"})
    downloader.app_download("containerd", {"charm": "cs:~containers/containerd-160"})
    mock_ch_downloader.assert_called_once_with("etcd", "etcd", channel="latest/edge")
    mock_cs_downloader.assert_called_once_with("containerd", "~containers/containerd-160")

    mock_ch_downloader.reset_mock()
    mock_cs_downloader.reset_mock()
    downloader.bundle_download()
    mock_ch_downloader.assert_not_called()
    mock_cs_downloader.assert_called_once_with(".bundle", "kubernetes-unit-test")


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
        "kubernetes-master",
        "kubernetes-worker",
    }
    assert downloader.bundles["test-overlay.yaml"]["applications"].keys() == {
        "calico",
        "flannel",
    }
    assert downloader.applications.keys() == {
        "calico",
        "containerd",
        "easyrsa",
        "etcd",
        "flannel",
        "kubernetes-master",
        "kubernetes-worker",
    }
