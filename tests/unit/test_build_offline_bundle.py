from pathlib import Path
import yaml

from shrinkwrap import build_offline_bundle, BundleDownloader

import mock


def test_build_offline_bundle(tmp_dir):
    root = Path(tmp_dir)
    charms = mock.MagicMock(spec_set=BundleDownloader)
    app_name = "etcd"

    with (Path(__file__).parent / "test_bundle.yaml").open() as fp:
        whole_bundle = yaml.safe_load(fp)
        whole_bundle["applications"] = {
            key: value for key, value in whole_bundle["applications"].items() if key == app_name
        }
        charms.bundles = {"bundle.yaml": whole_bundle}

    for resource in whole_bundle["applications"][app_name]["resources"]:
        rsc_path = root / "resources" / app_name / resource
        rsc_path.mkdir(parents=True)
        (rsc_path / "any-file-name").touch()

    for snap in ["core", "etcd"]:
        snap_path = root / "snaps" / snap
        snap_path.mkdir(parents=True)
        (snap_path / f"{snap}.tar.gz").touch()

    for container in [
        "cdkbot/microbot-amd64:latest",
        "pause-amd64:3.2",
        "defaultbackend-amd64:1.5",
    ]:
        cont_path = root / "containers" / f"{container}.tar.gz"
        cont_path.parent.mkdir(parents=True, exist_ok=True)
        cont_path.touch()

    build_offline_bundle(root, charms)

    for bundle in charms.bundles:
        bundle_file = root / bundle
        bundle_file.exists()
        created_yaml = yaml.safe_load(bundle_file.read_text())
        for app_name, app in created_yaml["applications"].items():
            for rsc_name, resource in app["resources"].items():
                assert resource.startswith("./"), f"{app_name}:{rsc_name} doesn't list local resource"

    readme = root / "README"
    assert readme.exists()
    text = readme.read_text()
    assert text.count("docker load") == 3, f"{readme} doesn't include 'docker load'"
    assert text.count("snap-store-proxy push-snap") == 2, f"{readme} doesn't include 'snap-store-proxy push-snap'"
    assert "juju deploy" in text, f"{readme} doesn't include 'juju deploy'"
    for bundle in charms.bundles:
        assert bundle in text, f"{readme} doesn't include {bundle}"

    deploy_sh = root / "deploy.sh"
    assert deploy_sh.exists()
