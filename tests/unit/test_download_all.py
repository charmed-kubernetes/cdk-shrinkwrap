from pathlib import Path

import yaml

from shrinkwrap import download, BundleDownloader

import mock


@mock.patch("shrinkwrap.BundleDownloader.app_download")
@mock.patch("shrinkwrap.SnapDownloader.download")
@mock.patch("shrinkwrap.ResourceDownloader.download")
@mock.patch("shrinkwrap.ResourceDownloader.list")
def test_download_method(resource_list, resource_dl, snap_dl, app_dl, tmp_dir):
    args = mock.MagicMock()
    args.overlay = []
    args.skip_snaps = False
    args.skip_resources = False
    args.skip_containers = False
    root = Path(tmp_dir)
    app_name = "etcd"

    with (Path(__file__).parent / "test_bundle.yaml").open() as fp:
        (root / "charms" / ".bundle").mkdir(parents=True)
        whole_bundle = yaml.safe_load(fp)
        whole_bundle["applications"] = {
            key: value for key, value in whole_bundle["applications"].items() if key == app_name
        }
        (root / "charms" / ".bundle" / "bundle.yaml").write_text(yaml.safe_dump(whole_bundle))

    with (Path(__file__).parent / "test_charm_config.yaml").open() as fp:
        (root / "charms" / app_name).mkdir(parents=True)
        (root / "charms" / app_name / "config.yaml").write_text(fp.read())

    app_dl.return_value = "cs:~containers/etcd"  # name of the charm, not the app
    resource_list.return_value = [
        {
            "Name": "core",
            "Type": "file",
            "Path": "core.snap",
            "Description": "Snap package of core",
            "Revision": 0,
            "Size": 0,
        },
        {
            "Name": "etcd",
            "Type": "file",
            "Path": "etcd.snap",
            "Description": "Snap package of etcd",
            "Revision": 3,
            "Size": 0,
        },
        {
            "Name": "snapshot",
            "Type": "file",
            "Path": "snapshot.tar.gz",
            "Description": "Tarball snapshot of an etcd clusters data.",
            "Revision": 0,
            "Size": 124,
        },
    ]

    charms = download(args, root)
    assert isinstance(charms, BundleDownloader)

    app_dl.assert_called_once_with(app_name, charms.applications[app_name])
    resource_list.assert_called_once_with(app_dl.return_value, args.channel)
    snap_dl.assert_called_once()
    resource_dl.assert_called_once()
    assert (Path(tmp_dir) / "resources" / "etcd" / "etcd" / "etcd.snap").is_symlink()
