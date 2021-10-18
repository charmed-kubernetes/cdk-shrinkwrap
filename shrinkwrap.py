#!/usr/bin/env python3

import argparse
import datetime
import json
from os import PathLike
from pathlib import Path
import re
import shlex
import shutil
from subprocess import check_call, check_output, Popen, STDOUT, PIPE
import sys

import requests
import semver
import yaml

shlx = shlex.split


def get_args():
    """Parse cli arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=str, nargs="?", help="the bundle to shrinkwrap")
    parser.add_argument(
        "--channel", "-c", default=None, help="the channel of the bundle"
    )
    parser.add_argument(
        "--arch", "-a", default=None, help="the target architecture of the bundle"
    )
    parser.add_argument(
        "--use_path", "-d", default=None, help="Use existing root path."
    )
    parser.add_argument(
        "--overlay",
        default=list(),
        action="append",
        help="Set of overlays to apply to the base bundle.",
    )
    return parser.parse_args()


class Downloader:
    def __init__(self, path: PathLike[str]):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def args(target: Path, channel: str, arch: str):
        r_args = ""
        if channel:
            r_args += f" --channel={channel}"
            target /= channel
        if arch:
            r_args += f" --architecture={arch}"
            target /= arch
        return r_args, target


class BundleDownloader(Downloader):
    def __init__(self, root: PathLike[str], args):
        super().__init__(Path(root) / "charms")
        self.bundle_path = self.path / ".bundle"
        self.args = args
        self.overlays = OverlayDownloader(self.bundle_path)
        self._cached_bundles = {}

    @property
    def bundles(self):
        if self._cached_bundles:
            return self._cached_bundles

        available_overlays = self.overlays.list
        for overlay in self.args.overlay:
            assert (
                overlay in available_overlays
            ), f"{overlay} is not a valid overlay bundle, choose any from {available_overlays}"

        all_bundles = ["bundle.yaml"] + self.args.overlay

        for bundle_name in all_bundles:
            if not (self.bundle_path / bundle_name).exists():
                self.overlays.download(bundle_name)
            with (self.bundle_path / bundle_name).open() as fp:
                bundle = yaml.safe_load(fp)
                self._cached_bundles[bundle_name] = bundle

        return self._cached_bundles

    @property
    def applications(self):
        return {
            app_name: self.bundles["bundle.yaml"]["applications"].get(app_name) or app
            for bundle in self.bundles.values()
            for app_name, app in bundle["applications"].items()
        }

    def bundle_download(self):
        bundle = self.args.bundle
        ch = bundle.startswith("ch:") or not bundle.startswith("cs:")
        if ch:
            self._charmhub_downloader(
                ".bundle", bundle.removeprefix("ch:"), channel=self.args.channel
            )
        else:
            self._charmstore_downloader(".bundle", bundle.removeprefix("cs:"))

    def app_download(self, appname: str, app: dict, **kwds):
        charm = app["charm"]
        ch = charm.startswith("ch:") or not charm.startswith("cs:")
        if ch:
            self._charmhub_downloader(appname, charm.removeprefix("ch:"), **kwds)
        else:
            self._charmstore_downloader(appname, charm.removeprefix("cs:"))
        return charm

    def _charmhub_downloader(self, name, resource, channel=None, arch=None):
        print(f'    Downloading "{resource}" from charm hub...')
        download_args, rsc_target = self.args(self.path / name, channel, arch)
        rsc_target.mkdir(parents=True, exist_ok=True)
        check_output(
            shlx(
                f"juju download {resource}{download_args} --filepath /tmp/archive.zip"
            ),
            stderr=STDOUT,
        )
        check_call(shlx(f"unzip -qq /tmp/archive.zip -d {rsc_target}"))
        check_call(shlx("rm /tmp/archive.zip"))
        return rsc_target

    def _charmstore_downloader(self, name, resource):
        print(f'    Downloading "{resource}" from charm store...')
        charmstore_url = "https://api.jujucharms.com/charmstore/v5"
        check_call(
            shlx(
                f"wget --quiet {charmstore_url}/{resource}/archive -O /tmp/archive.zip"
            )
        )
        rsc_target = self.path / name
        rsc_target.mkdir(parents=True, exist_ok=True)
        check_call(shlx(f"unzip -qq /tmp/archive.zip -d {rsc_target}"))
        check_call(shlx("rm /tmp/archive.zip"))
        return rsc_target


class OverlayDownloader(Downloader):
    URL = "https://api.github.com/repos/charmed-kubernetes/bundle/contents/overlays"

    def __init__(self, bundles_path: PathLike[str]):
        super().__init__(bundles_path)
        self._list_cache = None

    @property
    def list(self):
        if self._list_cache:
            return self._list_cache
        resp = requests.get(
            self.URL, headers={"Accept": "application/vnd.github.v3+json"}
        )
        self._list_cache = {
            obj.get("name"): obj.get("download_url") for obj in resp.json()
        }
        return self._list_cache

    def download(self, overlay):
        overlay_url = self.list[overlay]
        sys.stdout.write(f'    Downloading "{overlay}" from {overlay_url}...')
        with (self.path / overlay).open("w") as fp:
            fp.write(requests.get(overlay_url).text)
        print("Done")


class ContainerDownloader(Downloader):
    URL = "https://api.github.com/repos/charmed-kubernetes/bundle/contents/container-images"
    IMAGE_REPO = "rocks.canonical.com/cdk/"

    def __init__(self, root: PathLike[str]):
        super().__init__(Path(root) / "containers")

    def _revisions(self, channel_filter: str):
        if channel_filter == "latest/stable":
            # filter out non-released containers if the result is latest/stable
            def matches(n):
                return not channel_re.match(n)

            channel_re = re.compile(r"^(README)|(v.*-)")

        else:
            # filter in based on the channel_filter
            def matches(n):
                return channel_re.match(n)

            revision, _ = channel_filter.split("/", 1)
            channel_re = re.compile(rf"^v{re.escape(revision)}")

        resp = requests.get(
            self.URL, headers={"Accept": "application/vnd.github.v3+json"}
        )
        versions = [
            (
                obj.get("name").removeprefix("v").removesuffix(".txt"),
                obj.get("download_url"),
            )
            for obj in resp.json()
            if matches(obj.get("name"))
        ]
        return sorted(versions, key=lambda k: semver.VersionInfo.parse(k[0]))

    def _image_save(self, image):
        image_src = f"{self.IMAGE_REPO}{image}"
        target = Path(f"{self.path / image}.tar.gz")
        target.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout.write(f'    Downloading "{image}" from {self.IMAGE_REPO}...')
        with target.open("wb") as fp:
            check_call(shlx(f"sudo docker pull -q {image_src}"))
            p1 = Popen(shlx(f"sudo docker save {image_src}"), stdout=PIPE)
            p2 = Popen(shlx("gzip"), stdin=p1.stdout, stdout=fp)
            p1.stdout.close()
            p2.communicate()
            print("done")

    def _image_delete(self, image):
        image_src = f"{self.IMAGE_REPO}{image}"
        check_call(shlx(f"sudo docker rmi {image_src}"))

    def download(self, channel):
        _, latest_url = self._revisions(channel)[-1]
        print(f'    Downloading "{latest_url}" from github...')
        images = requests.get(latest_url).text.splitlines()
        for container_image in images:
            self._image_save(container_image)
        for container_image in images:
            self._image_delete(container_image)


class SnapDownloader(Downloader):
    def __init__(self, root: PathLike[str]):
        super().__init__(Path(root) / "snaps")
        self._downloaded = {}

    def download(self, snap, channel, arch) -> Path:
        snap_key = (snap, channel, arch)
        if snap_key not in self._downloaded:
            print(f'    Downloading snap "{snap}" from snap store...')
            download_args, snap_target = self.args(self.path / snap, channel, arch)
            snap_target.mkdir(parents=True, exist_ok=True)
            check_output(shlx(f"snap download {snap}{download_args}"), stderr=STDOUT)
            check_call(f"mv {snap}* {snap_target}", shell=True)
            self._downloaded[snap_key] = snap_target
        return self._downloaded[snap_key]


class ResourceDownloader(Downloader):
    URL = "https://api.jujucharms.com/charmstore/v5"

    def list(self, charm, channel):
        ch = charm.startswith("ch:") or not charm.startswith("cs:")
        if ch:
            raise NotImplementedError(
                "Charmhub doesn't support fetching resource lists"
            )
        else:
            resp = requests.get(
                f"{self.URL}/{charm.removeprefix('cs:')}/meta/resources",
                params={"channel": channel},
            )
        return json.loads(resp.text)

    def download(self, charm, name, revision, filename):
        (self.path / name).mkdir(parents=True, exist_ok=True)
        ch = charm.startswith("ch:") or not charm.startswith("cs:")
        target = self.path / name / filename
        if ch:
            raise NotImplementedError("Charmhub doesn't support fetching resources")
        else:
            url = f"{self.URL}/{charm.removeprefix('cs:')}/resource/{name}/{revision}"
            print(
                f"    Downloading resource {name} from charm store revision {revision}..."
            )
            check_call(shlx(f"wget --quiet {url} -O {target}"))
        return target


def charm_channel(app, charm_path) -> str:
    # Try to get channel from config
    with (charm_path / "config.yaml").open() as stream:
        config = yaml.safe_load(stream)
        try:
            channel = config["options"]["channel"]["default"]
        except KeyError:
            channel = "auto"
        if channel == "auto":
            channel = "latest/stable"

    # Check if there's a channel override in the bundle
    try:
        channel = app["options"]["channel"]
    except KeyError:
        pass
    return channel


def build_offline_bundle(root, charms: BundleDownloader):
    empty_snap = "./resources/.empty.snap"
    (root / empty_snap).touch(exist_ok=True)

    def update_resources(app_name, rsc):
        def resource_file(name):
            p = (root / "resources" / app_name / name).glob("*")
            root_path = next(p, empty_snap)  # use either downloaded file or empty_snap
            return root_path and str(root_path).replace(str(root), ".")

        return {name: resource_file(name) for name in rsc}

    def update_app(app_name, app):
        if app:
            app.update(
                {
                    "charm": "./" + str(Path("charms") / app_name),
                    "resources": update_resources(app_name, app.get("resources", [])),
                }
            )
        return app

    # create a bundle.yaml with links to local charms and resources
    deploy_args = ""
    for bundle_name, bundle in charms.bundles.items():
        created_bundle = dict(bundle)
        created_bundle["applications"] = {
            app_name: update_app(app_name, app)
            for app_name, app in bundle["applications"].items()
        }

        with (root / bundle_name).open("w") as fp:
            yaml.safe_dump(created_bundle, fp)

        is_trusted = any(
            app.get("trust") for app in bundle["applications"].values() if app
        )
        is_overlay = bundle_name != "bundle.yaml"

        if is_overlay:
            deploy_args += f" --overlay {bundle_name}"
        else:
            deploy_args += f" {bundle_name}"

        if is_trusted:
            deploy_args += " --trust"

    deploy_sh = root / "deploy.sh"
    deploy_sh.touch()
    deploy_sh.chmod(mode=0o755)
    bundle_list = charms.bundles.keys()
    deploy_sh.write_text("#!/bin/bash\n")
    deploy_sh.write_text(f"juju deploy{deploy_args}")


def download(args, root):
    snaps = SnapDownloader(root)
    charms = BundleDownloader(root, args)
    print("Bundles")
    charms.bundle_download()
    k8s_master_channel = None

    # For each application, download the charm, resources, and snaps.
    for app_name, app in charms.applications.items():
        print(app_name)
        charm_id = charms.app_download(app_name, app)

        charm = charm_id.rpartition("-")[0]
        app_channel = charm_channel(app, root / "charms" / app_name)
        if "kubernetes-master" in charm_id:
            k8s_master_channel = app_channel

        # Download each resource or snap.
        resources = ResourceDownloader(root / "resources" / app_name)
        for resource in resources.list(charm, args.channel):
            # Create the filename from the snap Name and Path extension. Use this instead of just Path because
            # multiple resources can have the same names for Paths.
            path = resource["Path"]

            # If it's a snap, download it from the store.
            if path.endswith(".snap"):
                # If the current resource is the core snap, ignore channel
                # and instead always download from stable.
                snap_channel = app_channel if resource["Name"] != "core" else "stable"

                # Path without .snap extension is currently a match for the name in the snap store. This may not always
                # be the case.
                snap = Path(path).stem

                # Download the snap and move it into position.
                snap_path = snaps.download(snap, snap_channel, args.arch)
                for file in snap_path.glob("*"):
                    check_call(shlx(f"ln -r -s {file} {resources.path}"))
            else:
                # This isn't a snap, do it the easy way.
                name = resource["Name"]
                revision = resource["Revision"]
                resource["filepath"] = resources.download(charm, name, revision, path)

    if k8s_master_channel:
        # Download the Container Images based on the kubernetes-master channel
        print("Containers")
        containers = ContainerDownloader(root)
        containers.download(k8s_master_channel)

    return charms


def main():
    args = get_args()
    skip_download = False

    if args.use_path:
        root = Path(args.use_path)
        assert root.exists(), f"Path {args.use_path} Doesn't Exist"
        skip_download = True
    elif args.channel:
        # Create a temporary dir.
        root = Path("build") / "{}-{}-{:%Y-%m-%d-%H-%M-%S}".format(
            args.bundle, args.channel, datetime.datetime.now()
        )
    else:
        # Create a temporary dir.
        root = Path("build") / "{}-{:%Y-%m-%d-%H-%M-%S}".format(
            args.bundle, datetime.datetime.now()
        )

    if not skip_download:
        bundle = download(args, root)
    else:
        bundle = BundleDownloader(root, args)

    # Generate a new bundle.yaml for deployment
    sys.stdout.write("Writing offline bundle.yaml ...")
    build_offline_bundle(root, bundle)
    print("done")

    # Make the tarball.
    sys.stdout.write("Writing tarball ...")
    check_call(
        shlx(
            f'tar -czf {root}.tar.gz -C build/ {root.relative_to("build")}  --force-local'
        )
    )
    # shutil.rmtree(root)
    print("done")


if __name__ == "__main__":
    main()
