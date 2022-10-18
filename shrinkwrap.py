#!/usr/bin/env python3

import argparse
import datetime
from collections import namedtuple
from collections.abc import Sequence
from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import re
from retry import retry
import shlex
import shutil
from subprocess import check_call, check_output, Popen, STDOUT, PIPE, CalledProcessError
import sys
from typing import Optional
import zipfile

import jinja2
import requests
import semver
import yaml

shlx = shlex.split


@contextmanager
def status(msg):
    sys.stdout.write(f"    {msg} ... ")
    sys.stdout.flush()
    yield
    print("done")


def remove_prefix(str_o, prefix):
    if str_o.startswith(prefix):
        return str_o[len(prefix) :]
    return str_o


def remove_suffix(str_o, suffix):
    if str_o.endswith(suffix):
        return str_o[: -len(suffix)]
    return str_o


def get_args():
    """Parse cli arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=str, help="the bundle to shrinkwrap")
    parser.add_argument("--channel", "-c", default=None, help="the channel of the bundle")
    parser.add_argument("--arch", "-a", default=None, help="the target architecture of the bundle")
    parser.add_argument(
        "--overlay",
        default=list(),
        action="append",
        help="Set of overlays to apply to the base bundle.",
    )
    parser.add_argument("--use_path", "-d", default=None, help="Reuse existing downloaded shrinkwrap path")
    parser.add_argument("--skip-resources", action="store_true", help="Skip downloading attached charm resources")
    parser.add_argument("--skip-snaps", action="store_true", help="Skip downloading required charm snaps")
    parser.add_argument("--skip-containers", action="store_true", help="Skip downloading container images")
    parser.add_argument("--skip-tar-gz", action="store_true", help="Skip creating a tar.gz in the ./build folder")
    return parser.parse_args()


class Downloader:
    def __init__(self, path):
        """
        @param path: PathLike[str]
        """
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._downloaded = {}

    @staticmethod
    def to_args(target: Path, channel: Optional[str] = None, arch: Optional[str] = None):
        r_args = ""
        if channel:
            r_args += f" --channel={channel}"
            target /= channel
        if arch:
            r_args += f" --architecture={arch}"
            target /= arch
        return r_args, target


class StoreDownloader(Downloader):
    CS_URL = "https://api.jujucharms.com/charmstore/v5"
    CH_URL = "https://api.charmhub.io/v2"

    def _charmhub_info(self, name, **query):
        url = f"{self.CH_URL}/charms/info/{name}"
        resp = requests.get(url, params=query)
        return resp.json()


class BundleDownloader(StoreDownloader):
    def __init__(self, root, args):
        """
        @param root: PathLike[str]
        """
        super().__init__(Path(root) / "charms")
        self.bundle_path = self.path / ".bundle"
        self.args = args
        self.overlays = OverlayDownloader(self.bundle_path)
        self._cached_bundles = {}

    @property
    def bundles(self):
        if self._cached_bundles:
            return self._cached_bundles

        for overlay in self.args.overlay:
            assert (
                overlay in self.overlays.list
            ), f"{overlay} is not a valid overlay bundle, choose any from {self.overlays.list}"

        all_bundles = ["bundle.yaml"] + self.args.overlay
        self.bundle_download()

        for bundle_name in all_bundles:
            if bundle_name != "bundle.yaml":
                self.overlays.download(bundle_name)
            with (self.bundle_path / bundle_name).open() as fp:
                bundle = yaml.safe_load(fp)
                self._cached_bundles[bundle_name] = bundle

        return self._cached_bundles

    @staticmethod
    def apps_or_svcs(_bundle):
        return _bundle.get("applications") or _bundle.get("services")

    @property
    def applications(self):
        return {
            app_name: self.apps_or_svcs(self.bundles["bundle.yaml"]).get(app_name) or app
            for bundle in self.bundles.values()
            for app_name, app in self.apps_or_svcs(bundle).items()
        }

    def bundle_download(self):
        bundle, channel = self.args.bundle, self.args.channel
        return self._downloader(bundle, Path(".bundle") / "bundle.yaml", channel)

    def app_download(self, appname: str, app: dict):
        charm, channel = app["charm"], app.get("channel")
        _, app_target = self.to_args(Path(appname), channel)
        path = self._downloader(charm, app_target / "metadata.yaml", channel)
        return charm, path.parent

    def _downloader(self, name, path, channel):
        ch = name.startswith("ch:") or not name.startswith("cs:")
        name = remove_prefix(remove_prefix(name, "ch:"), "cs:")
        target = self.path / path
        if target.exists():
            print(f'    Downloaded "{name}" already exists')
            return target

        extract = target.parent
        extract.mkdir(parents=True, exist_ok=True)
        if ch:
            self._charmhub_downloader(name, extract, channel=channel)
        else:
            self._charmstore_downloader(name, extract, channel=channel)
        return target

    def _charmhub_downloader(self, name, target, channel=None):
        with status(f'Downloading "{name} {channel}" from charm hub'):
            charm_info = self._charmhub_info(name, channel=channel, fields="default-release.revision.download.url")
            url = charm_info["default-release"]["revision"]["download"]["url"]
            resp = requests.get(url)
            zipfile.ZipFile(BytesIO(resp.content)).extractall(target)

    def _charmstore_downloader(self, name, target, channel=None):
        with status(f'Downloading "{name} {channel}" from charm store'):
            url = f"{self.CS_URL}/{name}/archive"
            resp = requests.get(url, params={"channel": channel})
            zipfile.ZipFile(BytesIO(resp.content)).extractall(target)


class OverlayDownloader(Downloader):
    GH_URL = "https://api.github.com/repos/charmed-kubernetes/bundle/contents/overlays"

    def __init__(self, bundles_path):
        """
        @param bundles_path: PathLike[str]
        """
        super().__init__(bundles_path)
        self._list_cache = None

    @property
    def list(self):
        if self._list_cache:
            return self._list_cache
        resp = requests.get(self.GH_URL, headers={"Accept": "application/vnd.github.v3+json"})
        self._list_cache = {obj.get("name"): obj.get("download_url") for obj in resp.json()}
        return self._list_cache

    def download(self, overlay):
        target = self.path / overlay
        if target.exists():
            print(f'    Downloaded "{overlay}" exists')
            return
        overlay_url = self.list[overlay]
        with status(f'Downloading "{overlay_url}" from github'):
            with target.open("w") as fp:
                fp.write(requests.get(overlay_url).text)


class ContainerDownloader(Downloader):
    URL = "https://api.github.com/repos/charmed-kubernetes/bundle/contents/container-images"
    IMAGE_REPO = "rocks.canonical.com/cdk/"

    def __init__(self, root):
        """
        @param root: PathLike[str]
        """
        super().__init__(Path(root) / "containers")

    def revisions(self, channel_filter: str):
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

        resp = requests.get(self.URL, headers={"Accept": "application/vnd.github.v3+json"})
        versions = [
            (
                remove_suffix(remove_prefix(obj.get("name"), "v"), ".txt"),
                obj.get("download_url"),
            )
            for obj in resp.json()
            if matches(obj.get("name"))
        ]
        return sorted(versions, key=lambda k: semver.VersionInfo.parse(k[0]))

    def _image_keys(self, image):
        if not image.startswith(self.IMAGE_REPO):
            image_src = f"{self.IMAGE_REPO}{image}"
        else:
            image_src, image = image, image[len(self.IMAGE_REPO) :]
        return image_src, image

    def _image_save(self, image):
        image_src, image = self._image_keys(image)
        target = Path(f"{self.path / image}.tar.gz")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as fp:
            with status(f'Downloading "{image}" from {self.IMAGE_REPO}'):
                check_call(shlx(f"docker pull -q {image_src}"))
                p1 = Popen(shlx(f"docker save {image_src}"), stdout=PIPE)
                p2 = Popen(shlx("gzip"), stdin=p1.stdout, stdout=fp)
                p1.stdout.close()
                p2.communicate()

    def _image_delete(self, image):
        image_src, image = self._image_keys(image)
        check_call(shlx(f"docker rmi {image_src}"))

    def download(self, channel):
        print("Containers")
        revisions = self.revisions(channel)
        assert revisions, f"No revisions matched the channel {channel}"
        _, latest_url = revisions[-1]

        with status(f'Downloading "{latest_url}" from github'):
            images = requests.get(latest_url).text.splitlines()
        for container_image in images:
            self._image_save(container_image)
        for container_image in images:
            self._image_delete(container_image)


class SnapDownloader(Downloader):
    def __init__(self, root):
        """
        @param root: PathLike[str]
        """
        super().__init__(Path(root) / "snaps")
        self.empty_snap = self.path / ".empty.snap"
        self.empty_snap.touch(exist_ok=True)

    @retry(CalledProcessError, tries=3, delay=2)
    def _fetch_snap(self, snap, args):
        out = check_output(
            shlx(f"snap-store-proxy fetch-snaps {snap}{args}"),
            stderr=STDOUT,
            text=True,
        )
        (tgz,) = re.findall(r"(\S+.tar.gz)", out)
        user = os.environ.get("USER")
        check_call(shlx(f"chown {user}:{user} {tgz}"))
        return tgz

    def mark_download(self, snap, channel, arch):
        """
        :rvalue: tuple[str, Path]
        """
        snap_key = snap, channel, arch
        if snap_key not in self._downloaded:
            self._downloaded[snap_key] = self.to_args(self.path / snap, channel, arch)
        return self._downloaded[snap_key]

    def download(self):
        print("Snaps")
        for (snap, channel, arch), (download_args, snap_target) in self._downloaded.items():
            if len(list(snap_target.glob("*.tar.gz"))):
                print(f'    Downloaded snap "{snap}" exists')
                continue
            with status(f'Downloading snap "{snap}" from snap store'):
                snap_target.mkdir(parents=True, exist_ok=True)
                tgz = self._fetch_snap(snap, download_args)
                check_call(shlx(f"mv {tgz} {snap_target}"))


class Resource(namedtuple("Resource", "name, type, path, revision, url_format")):
    @classmethod
    def from_charmstore(cls, baseurl, json):
        if isinstance(json, Sequence):
            return [cls.from_charmstore(baseurl, _) for _ in json]
        return cls(
            json["Name"],
            json["Type"],
            json["Path"],
            json["Revision"],
            f"{baseurl}/resource/{json['Name']}/{{revision}}",
        )

    @classmethod
    def from_charmhub(cls, json):
        if isinstance(json, Sequence):
            return [cls.from_charmhub(_) for _ in json]
        url_format = remove_suffix(json["download"]["url"], f"_{json['revision']}")
        return cls(
            json["name"],
            json["type"],
            json["filename"],
            json["revision"],
            f"{url_format}_{{revision}}",
        )

    @property
    def url(self):
        return self.url_format.format(revision=self.revision)


class ResourceDownloader(StoreDownloader):
    def __init__(self, root):
        """
        @param root: PathLike[str]
        """
        super().__init__(Path(root) / "resources")

    def list(self, charm, channel):
        ch = charm.startswith("ch:") or not charm.startswith("cs:")
        if ch:
            resp = self._charmhub_info(charm, channel=channel, fields="default-release.resources")
            resources = Resource.from_charmhub(resp["default-release"]["resources"])
        else:
            name = remove_prefix(charm, "cs:")
            resp = requests.get(
                f"{self.CS_URL}/{name}/meta/resources",
                params={"channel": channel},
            )
            resources = Resource.from_charmstore(f"{self.CS_URL}/{name}", resp.json())
        return resources

    def mark_download(self, app, charm, resource) -> Path:
        resource_key = app, charm, resource
        if resource_key not in self._downloaded:
            self._downloaded[resource_key] = self.path / app / resource.name / resource.path
        return self._downloaded[resource_key]

    def download(self):
        print("Resources")
        for (app, charm, resource), target in self._downloaded.items():
            if target.exists():
                print(f"    Downloaded resource {resource.name} - {resource.revision} exists")
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with status(f"Downloading {charm} resource {resource.name} @ revision {resource.revision}"):
                check_call(shlx(f"wget --quiet {resource.url} -O {target}"))


def charm_snap_channel(app, charm_path) -> str:
    # Try to get channel from config
    with (charm_path / "config.yaml").open() as stream:
        config = yaml.safe_load(stream)
        try:
            channel = config["options"]["channel"]["default"]
        except KeyError:
            channel = "auto"

    if channel == "auto":
        channel = "stable"

    # Check if there's a channel override in the bundle
    try:
        channel = app["options"]["channel"]
    except KeyError:
        pass
    return channel


def download(args, root):
    charms = BundleDownloader(root, args)
    snaps = SnapDownloader(root)
    resources = ResourceDownloader(root)
    print("Bundles")
    k8s_cp_channel = None

    # For each application, download the charm, resources, and snaps.
    for app_name, app in charms.applications.items():
        charm, charm_path = charms.app_download(app_name, app)
        snap_channel = charm_snap_channel(app, charm_path)
        charm_channel = app.get("channel")
        if charm in ["kubernetes-control-plane", "kubernetes-master"]:  # wokeignore:rule=master
            k8s_cp_channel = snap_channel

        # Download each resource or snap.
        for resource in resources.list(charm, charm_channel):
            # Create the filename from the snap Name and Path extension. Use this instead of just Path because
            # multiple resources can have the same names for Paths.
            path = resource.path
            name = resource.name

            # If it's a snap, download it from the store.
            if path.endswith(".snap"):
                # If the current resource is the core snap, ignore channel
                # and instead always download from stable.
                snap_channel = snap_channel if name != "core" else "stable"

                # Path without .snap extension is currently a match for the name in the snap store. This may not always
                # be the case.
                snap = Path(path).stem

                # Download the snap and move it into position.
                snaps.mark_download(snap, snap_channel, args.arch)

                # Ensure an empty snap shows up in the resource path
                snap_resource = resources.path / app_name / name / path
                if not snap_resource.is_symlink():
                    snap_resource.parent.mkdir(parents=True, exist_ok=True)
                    check_call(shlx(f"ln -r -s {snaps.empty_snap} {snap_resource}"))
            else:
                # This isn't a snap, pull the resource from the appropriate store
                # use the bundle provided resource revision if available
                resource_rev = app.get("resources", {}).get(resource.name)
                resource_rev = resource_rev or resource.revision
                resource = Resource(resource.name, resource.type, resource.path, resource_rev, resource.url_format)
                resources.mark_download(app_name, charm, resource)

    base_snaps = ["core18", "core20", "lxd", "snapd"]
    for snap in base_snaps:
        snaps.mark_download(snap, "stable", None)

    if not args.skip_snaps:
        snaps.download()

    if not args.skip_resources:
        resources.download()

    if k8s_cp_channel and not args.skip_containers:
        # Download the Container Images based on the kubernetes-control-plane channel
        containers = ContainerDownloader(root)
        containers.download(k8s_cp_channel)

    return charms


def build_offline_bundle(root, charms: BundleDownloader):
    def local_path(build_path):
        """
        @param build_path: PathLike[str]
        """
        return str(build_path).replace(str(root), ".")

    def update_resources(app_name, rsc):
        def resource_file(name):
            rsc_path = (root / "resources" / app_name / name).glob("*")
            # each resource path should contain one file, take the first one
            # if this resource is a snap, it will point to an symlink to "./snaps/empty.snap"
            try:
                return local_path(next(rsc_path))
            except StopIteration:
                return None

        return {name: resource_file(name) or rev for name, rev in rsc.items()}

    def update_app(app_name, app):
        if app:
            _, target = Downloader.to_args(root / "charms" / app_name, app.get("channel"))
            # Load the resource definition from the current bundle if possible
            # This will be a map of resource-name to resource numerical version
            resources = app.get("resources")
            if not resources:
                # Load the resource from the local charm
                # This will be a map of resource-name to resource metadata
                resources = yaml.safe_load((target / "metadata.yaml").open()).get("resources", {})
            app.update(
                {
                    "charm": local_path(target),
                    "resources": update_resources(app_name, resources),
                }
            )
        return app

    # create a bundle.yaml with links to local charms and resources
    deploy_args = ""
    for bundle_name, bundle in charms.bundles.items():
        created_bundle = dict(bundle)
        created_bundle["applications"] = {
            app_name: update_app(app_name, app) for app_name, app in BundleDownloader.apps_or_svcs(bundle).items()
        }

        with (root / bundle_name).open("w") as fp:
            yaml.safe_dump(created_bundle, fp)

        is_trusted = any(app.get("trust") for app in BundleDownloader.apps_or_svcs(bundle).values() if app)
        is_overlay = bundle_name != "bundle.yaml"

        if is_overlay:
            deploy_args += f" --overlay ./{bundle_name}"
        else:
            deploy_args += f" ./{bundle_name}"

        if is_trusted:
            deploy_args += " --trust"

    push_snaps = root / "push_snaps.sh"
    push_snaps_tmp = Path(__file__).parent / "templates" / "push_snaps.sh.j2"
    template = jinja2.Template(push_snaps_tmp.read_text())
    push_snaps.write_text(template.render(snaps=[local_path(snap) for snap in (root / "snaps").glob("**/*.tar.gz")]))
    push_snaps.chmod(mode=0o755)

    containers_path = root / "containers"
    push_containers = root / "push_container_images.sh"
    push_containers_tmp = Path(__file__).parent / "templates" / "push_container_images.sh.j2"
    template = jinja2.Template(push_containers_tmp.read_text())
    push_containers.write_text(
        template.render(
            containers={
                f"{container_tgz.relative_to(containers_path)}".replace(".tar.gz", ""): local_path(container_tgz)
                for container_tgz in containers_path.glob("**/*.tar.gz")
            },
            IMAGE_REPO=ContainerDownloader.IMAGE_REPO,
        )
    )
    push_containers.chmod(mode=0o755)

    deploy_readme = root / "README"
    readme_tmp = Path(__file__).parent / "templates" / "README.j2"
    template = jinja2.Template(readme_tmp.read_text())
    deploy_readme.write_text(template.render(deploy_args=deploy_args))

    deploy_sh = root / "deploy.sh"
    deploy_sh.write_text("#!/bin/bash\n" "cat ./README\n")
    deploy_sh.chmod(mode=0o755)


def main():
    args = get_args()

    if args.use_path:
        root = Path(args.use_path)
        assert root.exists(), f"Path {args.use_path} Doesn't Exist"
    elif args.channel:
        # Create a temporary dir.
        root = Path("build") / "{}-{}-{:%Y-%m-%d-%H-%M-%S}".format(args.bundle, args.channel, datetime.datetime.now())
    else:
        # Create a temporary dir.
        root = Path("build") / "{}-{:%Y-%m-%d-%H-%M-%S}".format(args.bundle, datetime.datetime.now())

    bundle = download(args, root)

    # Generate a new bundle.yaml for deployment
    with status("Writing offline bundle.yaml"):
        build_offline_bundle(root, bundle)

    # Make the tarball.
    if not args.skip_tar_gz:
        with status(f"Writing tarball {root}.tar.gz"):
            check_call(shlx(f'tar -czf {root}.tar.gz -C build/ {root.relative_to("build")} --force-local'))
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
