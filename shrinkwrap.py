#!/usr/bin/env python3

import argparse
import datetime
import json
from pathlib import Path
import shlex
import shutil
from subprocess import check_call, check_output, STDOUT
import sys

import requests
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
    return parser.parse_args()


def build_offline_bundle(root, bundle):
    # create a bundle.yaml with links to local charms and resources
    created_bundle = dict(bundle)
    empty_snap = "./resources/.empty.snap"
    (root / empty_snap).touch(exist_ok=True)

    def update_resources(app_name, rsc):
        def resource_file(name):
            p = (root / "resources" / app_name / name).glob("*")
            root_path = next(p, empty_snap)  # use either downloaded file or empty_snap
            return root_path and str(root_path).replace(str(root), ".")

        return {name: resource_file(name) for name in rsc}

    def update_app(app_name, app):
        app.update(
            {
                "charm": "./" + str(Path("charms") / app_name),
                "resources": update_resources(app_name, app["resources"]),
            }
        )
        return app

    created_bundle["applications"] = {
        app_name: update_app(app_name, app)
        for app_name, app in bundle["applications"].items()
    }

    with (root / "bundle.yaml").open("w") as fp:
        yaml.safe_dump(created_bundle, fp)

    deploy_sh = root / 'deploy.sh'
    deploy_sh.touch()
    deploy_sh.chmod(mode=0o755)
    deploy_sh.write_text(
        """#!/bin/bash\n"""
        """juju deploy ./bundle.yaml"""
    )


class Downloader:
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


class CharmDownloader(Downloader):
    def __init__(self, root: Path):
        self.charm_path = root / "charms"
        self.bundle_path = self.charm_path / ".bundle"
        self.charm_path.mkdir(parents=True, exist_ok=True)

    @property
    def bundle(self):
        with (self.bundle_path / "bundle.yaml").open() as fp:
            return yaml.safe_load(fp)

    def bundle_download(self, bundle: str, channel: str):
        ch = bundle.startswith("ch:") or not bundle.startswith("cs:")
        if ch:
            self._charmhub_downloader(
                ".bundle", bundle.removeprefix("ch:"), channel=channel
            )
        else:
            self._charmstore_downloader(".bundle", bundle.removeprefix("cs:"))
        return self.bundle

    def app_download(self, appname: str, app: dict, **kwds):
        charm = app["charm"]
        ch = charm.startswith("ch:") or not charm.startswith("cs:")
        if ch:
            self._charmhub_downloader(appname, charm.removeprefix("ch:"), **kwds)
        else:
            self._charmstore_downloader(appname, charm.removeprefix("cs:"))
        return charm

    def _charmhub_downloader(self, name, resource, channel=None, arch=None):
        charm_key = (resource, channel, arch)
        print(f'    Downloading "{resource}" from charm hub...')
        download_args, rsc_target = self.args(self.charm_path / name, channel, arch)
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
        download_args, rsc_target = "", self.charm_path / name
        rsc_target.mkdir(parents=True, exist_ok=True)
        charmstore_url = "https://api.jujucharms.com/charmstore/v5"
        check_call(
            shlx(
                f"wget --quiet {charmstore_url}/{resource}/archive -O /tmp/archive.zip"
            )
        )
        check_call(shlx(f"unzip -qq /tmp/archive.zip -d {rsc_target}"))
        check_call(shlx("rm /tmp/archive.zip"))
        return rsc_target


class SnapDownloader(Downloader):
    def __init__(self, root: Path):
        self.snap_path = root / "snaps"
        self.snap_path.mkdir(parents=True, exist_ok=True)
        self._downloaded = {}

    def download(self, snap, channel, arch) -> Path:
        snap_key = (snap, channel, arch)
        if snap_key not in self._downloaded:
            print(f'    Downloading snap "{snap}" from snap store...')
            download_args, snap_target = self.args(self.snap_path / snap, channel, arch)
            snap_target.mkdir(parents=True, exist_ok=True)
            check_output(shlx(f"snap download {snap}{download_args}"), stderr=STDOUT)
            check_call(f"mv {snap}* {snap_target}", shell=True)
            self._downloaded[snap_key] = snap_target
        return self._downloaded[snap_key]


class ResourceDownloader(Downloader):
    def __init__(self, resource_path: Path):
        self.path = resource_path
        self.path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def list(charm, channel):
        ch = charm.startswith("ch:") or not charm.startswith("cs:")
        if ch:
            raise NotImplementedError(
                "Charmhub doesn't support fetching resource lists"
            )
        else:
            resp = requests.get(
                f'https://api.jujucharms.com/charmstore/v5/{charm.removeprefix("cs:")}/meta/resources',
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
            url = f'https://api.jujucharms.com/charmstore/v5/{charm.removeprefix("cs:")}/resource/{name}/{revision}'
            print(
                f"    Downloading resource {name} from charm store revision {revision}..."
            )
            check_call(shlx(f"wget --quiet {url} -O {target}"))
        return target


def download(args, root):
    snaps = SnapDownloader(root)
    charms = CharmDownloader(root)
    bundle = charms.bundle_download(args.bundle, args.channel)

    # For each application, download the charm, resources, and snaps.
    for app_name, app in bundle["applications"].items():
        print(app_name)
        charm_id = charms.app_download(app_name, app)

        # If this is a subordinate charm, we won't need a machine for it.
        with (root / "charms" / app_name / "metadata.yaml").open() as stream:
            metadata = yaml.safe_load(stream)

        # Get the charm resources metadata.
        charm = charm_id.rpartition("-")[0]

        # Download each resource or snap.
        resources = ResourceDownloader(root / "resources" / app_name)
        for resource in resources.list(charm, args.channel):
            # Create the filename from the snap Name and Path extension. Use this instead of just Path because
            # multiple resources can have the same names for Paths.
            path = resource["Path"]

            # If it's a snap, download it from the store.
            if path.endswith(".snap"):
                channel = "stable"
                charm_path = root / "charms" / app_name

                # If the current resource is the core snap, ignore channel
                # and instead always download from stable.
                if resource["Name"] != "core":
                    # Try to get channel from config
                    with (charm_path / "config.yaml").open() as stream:
                        config = yaml.safe_load(stream)
                        try:
                            channel = config["options"]["channel"]["default"]
                        except KeyError:
                            pass
                        channel = "stable" if channel == "auto" else channel

                    # Check if there's a channel override in the bundle
                    try:
                        channel = app["options"]["channel"]
                    except KeyError:
                        pass

                # Path without .snap extension is currently a match for the name in the snap store. This may not always
                # be the case.
                snap = Path(path).stem

                # Download the snap and move it into position.
                snap_path = snaps.download(snap, channel, args.arch)
                for file in snap_path.glob("*"):
                    check_call(shlx(f"ln -r -s {file} {resources.path}"))
            else:
                # This isn't a snap, do it the easy way.
                name = resource["Name"]
                revision = resource["Revision"]
                resource["filepath"] = resources.download(charm, name, revision, path)

    # Download the core snap.
    print("Downloading the core snap...")
    snaps.download("core", "stable", args.arch)
    return bundle


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
        bundle = CharmDownloader(root).bundle

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
#    shutil.rmtree(root)
    print("done")


if __name__ == "__main__":
    main()
