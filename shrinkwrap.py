#!/usr/bin/env python3

import os
import argparse
import json
import yaml
from pathlib import Path
import requests
import stat
import shutil
import shlex
import datetime
from subprocess import check_call, check_output, STDOUT

shsplit = shlex.split


def get_args():
    """ Parse cli arguments. """
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=str, nargs='?',
                        help='the bundle to shrinkwrap')
    parser.add_argument('--channel', '-c', default=None,
                        help='the channel of the bundle')
    parser.add_argument('--arch', '-a', default=None,
                        help='the target architecture of the bundle')
    return parser.parse_args()


def get_machine_count(applications_to_deploy, subordinates):
    machineCount = 0
    for appname, app in applications_to_deploy.items():
        if appname not in subordinates:
            machineCount += app['NumUnits']

    return machineCount


def build_deploy_script(script_filename, bundle, subordinates, applications_to_deploy=None):
    # Figure out how many machines we'll need.
    if applications_to_deploy:
        # when applications_to_deploy is set, we're writing out scripts to add a single machine
        # so we shouldn't use the unit count for that
        machineCount = 1
    else:
        machineCount = get_machine_count(bundle['applications'], subordinates)

    deploy = []
    relate = []

    # Commands for creating machines and waiting on them to be live..
    deploy.append("MACHINES=$(juju add-machine -n %d 2>&1|awk '{print $3}')" % machineCount)
    deploy.append("set +x")
    deploy.append(
        "until [[ %d -eq `juju machines | grep started | wc -l` ]]; do sleep 1; echo Waiting for machines to start...; done" % machineCount)  # noqa
    deploy.append("set -x")

    # Let's just install snap core on everything. TODO: don't do this on machines we don't need snaps on.
    deploy.append('for machine in $MACHINES; do')
    deploy.append('  juju scp %s $machine:' % (os.path.join('resources', 'core.snap')))
    deploy.append('  juju run --machine $machine "sudo snap install --dangerous /home/ubuntu/core.snap"')
    deploy.append('done')
    deploy.append('MACHINE_LIST=($MACHINES)')

    if applications_to_deploy:
        # Commands for adding a unit to machines.
        machine_index = 0
        for appname, app in bundle['applications'].items():
            if appname not in applications_to_deploy:
                continue
            deploy.append("juju add-unit --to ${MACHINE_LIST[%d]} ./charms/%s" % (machine_index, appname))
            machine_index += 1
    else:
        # Commands for deploying charms to machines.
        machine_index = 0
        for appname, app in bundle['applications'].items():
            resource_list = []
            for resource in app['resources']:
                resource_list.append("--resource %s=%s" % (resource['Name'],
                                                           os.path.join('.', 'resources',
                                                                        appname, resource['filename'])))
            if appname in subordinates:
                deploy.append("juju deploy %s ./charms/%s" % (" ".join(resource_list), appname))
            else:
                num_list = []
                for x in range(app['NumUnits']):
                    num_list.append("${MACHINE_LIST[%d]}" % (machine_index))
                    machine_index += 1

                deploy.append("juju deploy -n {} {} --to {} ./charms/{}".format(app['NumUnits'],
                                                                                " ".join(resource_list),
                                                                                ",".join(num_list),
                                                                                appname))

        # Commands for relating charms.
        for relation in bundle['Relations']:
            relate.append('juju relate %s %s' % (relation[0], relation[1]))

    # Write the deployment script.
    with open(script_filename, 'w') as sh:
        sh.write('#!/bin/bash\n\n')
        sh.write('set -eux\n\n')
        for cmd in deploy:
            sh.write(cmd + '\n')
        for cmd in relate:
            sh.write(cmd + '\n')

    # Make the deployment script executable.
    st = os.stat(script_filename)
    os.chmod(script_filename, st.st_mode | stat.S_IEXEC)


class Downloader:
    @staticmethod
    def args(target: Path, channel: str, arch: str):
        r_args = ""
        if channel:
            r_args += f' --channel={channel}'
            target /= channel
        if arch:
            r_args += f' --architecture={arch}'
            target /= arch
        return r_args, target


class CharmResource(Downloader):
    def __init__(self, root: Path):
        self.charm_path = root / 'charms'
        self.charm_path.mkdir(parents=True, exist_ok=True)

    def bundle_download(self, bundle: str, channel: str):
        ch = bundle.startswith("ch:") or not bundle.startswith("cs:")
        if ch:
            bundle_path = self._charmhub_downloader('bundle', bundle, channel=channel)
        else:
            bundle_path = self._charmstore_bundle('bundle', bundle, channel=channel)
        with (bundle_path/"bundle.yaml").open() as fp:
            return yaml.safe_load(fp)

    def app_download(self, appname: str, app: str, **kwds):
        charm = app['Charm'][3:]
        ch = app['Charm'].startswith("ch:") or not app['Charm'].startswith("cs:")
        if ch:
            self._charmhub_downloader(appname, charm, **kwds)
        else:
            self._charmstore_charm(appname, charm)
        return charm

    def _charmhub_downloader(self, name, resource, channel=None, arch=None):
        charm_key = (resource, channel, arch)
        print(f'    Downloading "{resource}" from charm hub...')
        download_args, rsc_target = self.args(self.charm_path / name, channel, arch)
        rsc_target.mkdir(parents=True, exist_ok=True)
        check_output(shsplit(f'juju download {resource}{download_args} --filepath /tmp/archive.zip'), stderr=STDOUT)
        check_call(shsplit(f'unzip -qq /tmp/archive.zip -d {rsc_target}'))
        check_call(shsplit('rm /tmp/archive.zip'))
        return rsc_target

    def _charmstore_charm(self, appname, charm):
        print(f'    Downloading charm "{charm}" from charm store...')
        download_args, charm_target = '', self.charm_path / appname
        charm_target.mkdir(parents=True, exist_ok=True)
        charmstore_url = "https://api.jujucharms.com/charmstore/v5"
        check_call(shsplit(f'wget --quiet {charmstore_url}/{charm}/archive -O /tmp/archive.zip'))
        check_call(shsplit(f'unzip -qq /tmp/archive.zip -d {charm_target}'))
        check_call(shsplit('rm /tmp/archive.zip'))
        return charm_target

    def _charmstore_bundle(self, bundle_path, bundle, channel):
        print(f'    Downloading bundle "{bundle}" from charm store...')
        download_args, target = '', self.charm_path / bundle_path
        target.mkdir(parents=True, exist_ok=True)
        resp = requests.get('https://api.jujucharms.com/charmstore/v5/meta/bundle-metadata',
                            params={'id': bundle, 'channel': channel})
        bundle_data = json.loads(resp.text)[bundle]
        with (target/'bundle.yaml').open('w') as fp:
            yaml.safe_dump(bundle_data, fp)
        return target


class SnapResources(Downloader):
    def __init__(self, root: Path):
        self.snap_path = root / 'snaps'
        self.snap_path.mkdir(parents=True, exist_ok=True)
        self._downloaded = {}

    def download(self, snap, channel, arch):
        snap_key = (snap, channel, arch)
        if snap_key not in self._downloaded:
            print(f'    Downloading snap "{snap}" from snap store...')
            download_args, snap_target = self.args(self.snap_path / snap, channel, arch)
            snap_target.mkdir(parents=True, exist_ok=True)
            check_output(shsplit(f'snap download {snap}{download_args}'), stderr=STDOUT)
            check_call(f'mv {snap}* {snap_target}', shell=True)
            self._downloaded[snap_key] = snap_target / snap
        return self._downloaded[snap_key]


def main():
    args = get_args()

    # Create a temporary dir.
    if args.channel:
        root = Path('{}-{}-{:%Y-%m-%d-%H-%M-%S}'.format(args.bundle, args.channel, datetime.datetime.now()))
    else:
        root = Path('{}-{:%Y-%m-%d-%H-%M-%S}'.format(args.bundle, datetime.datetime.now()))
    snaps = SnapResources(root)
    charms = CharmResource(root)

    bundle = charms.bundle_download(args.bundle, args.channel)

    # Keep track of subordinate applications.
    subordinates = []

    # For each application, download the charm, resources, and snaps.
    for appname, app in bundle['applications'].items():
        print(appname)

        # Create a path to store the charm and its resources.
        (root / 'resources' / appname).mkdir(parents=True)
        (root / 'charms' / appname).mkdir(parents=True)

        charm_id = charms.app_download(appname, app)

        # If this is a subordinate charm, we won't need a machine for it.

        with (root / 'charms' / appname / "metadata.yaml").open() as stream:
            metadata = yaml.safe_load(stream)
            if 'subordinate' in metadata and metadata['subordinate'] is True:
                subordinates.append(appname)

        # Get the charm resources metadata.
        charm = charm_id.rpartition('-')[0]
        resp = requests.get(
            'https://api.jujucharms.com/charmstore/v5/%s/meta/resources' % charm,
            params={'channel': args.channel}
        )
        resources = json.loads(resp.text)
        bundle['applications'][appname]['resources'] = resources

        # Download each resource or snap.
        for resource in resources:
            # Create the filename from the snap Name and Path extension. Use this instead of just Path because
            # multiple resources can have the same names for Paths.
            extension = os.path.splitext(resource['Path'])[1]
            filename = resource['Name'] + extension
            resource['filename'] = filename
            resource_path = root / 'resources' / appname
            charm_path = root / 'charms' / appname

            # If it's a snap, download it from the store.
            if resource['Path'].endswith('.snap'):
                channel = 'stable'

                # If the current resource is the core snap, ignore channel
                # and instead always download from stable.
                if resource['Name'] != 'core':
                    # Try to get channel from config
                    with (charm_path / 'config.yaml').open() as stream:
                        config = yaml.safe_load(stream)
                        if 'options' in config:
                            if 'channel' in config['options']:
                                # Might need to check if this is nonsensical
                                channel = config['options']['channel']['default']

                    # Check if there's a channel override in the bundle
                    if 'Options' in app:
                        if 'channel' in app['Options']:
                            channel = app['Options']['channel']

                # Path without .snap extension is currently a match for the name in the snap store. This may not always
                # be the case.
                snap = resource['Path'].replace('.snap', '')

                # Download the snap and move it into position.
                snap_path = snaps.download(snap, channel, args.arch)
                check_call(f'ln -s {snap_path}* {resource_path}', shell=True)

            # This isn't a snap, do it the easy way.
            else:
                name = resource['Name']
                revision = resource['Revision']
                url = 'https://api.jujucharms.com/charmstore/v5/%s/resource/%s/%d' % (charm, name, revision)
                print('    Downloading resource %s from charm store revision %s...' % (filename, revision))
                check_call(shsplit(f'wget --quiet {url} -O {resource_path / filename}'))

    print('Writing deploy scripts...')
    build_deploy_script(os.path.join(root, 'deploy.sh'), bundle, subordinates)
    print('    deploy.sh')
    for appname, app in bundle['applications'].items():
        script_filename = os.path.join(root, 'add-unit-{}.sh'.format(appname))
        app_to_deploy = {appname: app}
        build_deploy_script(script_filename, bundle, subordinates, app_to_deploy)
        print(f'    {script_filename}')

    # Download the core snap.
    print('Downloading the core snap...')
    snap_path = snaps.download("core", "stable", args.arch)
    check_call(f'ln -s {snap_path}* {root / "resources"}', shell=True)

    # Make the tarball.
    check_call(shsplit(f'tar -czf "{root}.tar.gz" "{root}" --force-local'))
    shutil.rmtree(root)

    print('Done.')


if __name__ == '__main__':
    main()
