from pathlib import Path

import yaml

from shrinkwrap import download, BundleDownloader, Resource

import mock


@mock.patch("shrinkwrap.BundleDownloader.app_download")
@mock.patch("shrinkwrap.SnapDownloader.download")
@mock.patch("shrinkwrap.ResourceDownloader.download")
@mock.patch("shrinkwrap.ResourceDownloader.list")
def test_download_method(resource_list, resource_dl, snap_dl, app_dl, tmpdir, test_bundle, test_charm_config):
    args = mock.MagicMock()
    args.overlay = []
    args.skip_snaps = False
    args.skip_resources = False
    args.skip_containers = False
    root = Path(tmpdir)
    app_name = "etcd"

    with test_bundle.file.open() as fp:
        (root / "charms" / ".bundle").mkdir(parents=True)
        whole_bundle = yaml.safe_load(fp)
        whole_bundle[test_bundle.apps] = {
            key: value for key, value in whole_bundle[test_bundle.apps].items() if key == app_name
        }
        (root / "charms" / ".bundle" / "bundle.yaml").write_text(yaml.safe_dump(whole_bundle))

    with test_charm_config.open() as fp:
        (root / "charms" / app_name / "latest/edge").mkdir(parents=True)
        (root / "charms" / app_name / "latest/edge/config.yaml").write_text(fp.read())

    app_dl.return_value = "etcd"  # name of the charm, not the app
    resource_list.return_value = [
        Resource("core", "file", "core.snap", 0, "https://api.jujucharms.com/charmstore/v5/etcd/resource/core/0"),
        Resource("etcd", "file", "etcd.snap", 3, "https://api.jujucharms.com/charmstore/v5/etcd/resource/etcd/3"),
        Resource(
            "snapshot",
            "file",
            "snapshot.tar.gz",
            0,
            "https://api.jujucharms.com/charmstore/v5/etcd/resource/snapshot/0",
        ),
    ]

    charms = download(args, root)
    assert isinstance(charms, BundleDownloader)

    app_dl.assert_called_once_with(app_name, charms.applications[app_name])
    resource_list.assert_called_once_with(app_dl.return_value, "latest/edge")
    snap_dl.assert_called_once()
    resource_dl.assert_called_once()
    assert (Path(tmpdir) / "resources" / "etcd" / "etcd" / "etcd.snap").is_symlink()
