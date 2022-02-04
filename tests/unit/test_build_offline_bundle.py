from pathlib import Path
import yaml

from shrinkwrap import build_offline_bundle, BundleDownloader

import mock


def test_build_offline_bundle(tmpdir, test_bundle):
    root = Path(tmpdir)
    charms = mock.MagicMock(spec_set=BundleDownloader)
    app_name = "etcd"
    apps = test_bundle.apps

    with test_bundle.file.open() as fp:
        whole_bundle = yaml.safe_load(fp)
        whole_bundle[apps] = {key: value for key, value in whole_bundle[apps].items() if key == app_name}
        charms.bundles = {"bundle.yaml": whole_bundle}

    for resource in whole_bundle[apps][app_name]["resources"]:
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
    assert "juju deploy" in text, f"{readme} doesn't include 'juju deploy'"
    for bundle in charms.bundles:
        assert bundle in text, f"{readme} doesn't include {bundle}"

    push_containers = root / "push_container_images.sh"
    assert push_containers.exists()
    text = push_containers.read_text()
    assert text.count("docker load") == 3, f"{push_containers} doesn't include 'docker load'"
    assert text.count("docker tag") == 3, f"{push_containers} doesn't include 'docker tag'"
    assert text.count("docker image push") == 3, f"{push_containers} doesn't include 'docker image push'"
    assert text.count("docker image remove") == 6, f"{push_containers} doesn't include 'docker image push'"

    push_snaps = root / "push_snaps.sh"
    assert push_snaps.exists()
    text = push_snaps.read_text()
    assert text.count("snap-store-proxy push-snap") == 2, f"{push_snaps} doesn't include 'snap-store-proxy push-snap'"

    deploy_sh = root / "deploy.sh"
    assert deploy_sh.exists()
