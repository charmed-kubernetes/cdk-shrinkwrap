#!/usr/bin/env python3

import os
import argparse
import json
import yaml
import requests
import stat
import shutil
import datetime
from subprocess import check_call, check_output, STDOUT


def get_args():
    ''' Parse cli arguments. '''
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=str, nargs='?',
                        help='the bundle to shrinkwrap')
    parser.add_argument('--channel', '-c', default=None,
                        help='the channel of the bundle')
    return parser.parse_args()


def main():
    args = get_args()

    # Fetch the bundle metadata.
    resp = requests.get('https://api.jujucharms.com/charmstore/v5/meta/bundle-metadata',
                        params={'id': args.bundle, 'channel': args.channel})
    bundle = json.loads(resp.text)[args.bundle]

    # Create a temporary dir.
    if args.channel:
        root = '{}-{}-{:%Y-%m-%d-%H-%M-%S}'.format(args.bundle, args.channel, datetime.datetime.now())
    else:
        root = '{}-{:%Y-%m-%d-%H-%M-%S}'.format(args.bundle, datetime.datetime.now())
    os.makedirs(root)
    os.makedirs('%s/charms' % root)
    os.makedirs('%s/resources' % root)

    # Storage for the script we'll generate later.
    deploycmds = []
    attachcmds = []
    relatecmds = []

    # For each application, download the charm, resources, and snaps.
    for appname, app in bundle['applications'].items():
        print(appname)

        # Get the charm ID without cs: prepended.
        id = app['Charm'][3:]

        # Download the charm and unzip it.
        print('    Downloading charm...')
        check_call(('wget --quiet https://api.jujucharms.com/charmstore/v5/%s/archive -O /tmp/archive.zip' % id).split())
        check_call(('unzip -qq /tmp/archive.zip -d %s/charms/%s' % (root, appname)).split())
        check_call('rm /tmp/archive.zip'.split())

        # Store a juju command for deploying the charm.
        deploycmds.append("juju deploy ./charms/%s" % appname)

        # Get the charm resources metadata.
        resp = requests.get('https://api.jujucharms.com/charmstore/v5/%s/meta/resources' % id)
        resources = json.loads(resp.text)

        # Create a path to store the charm resources.
        os.makedirs(os.path.join(root, 'resources', appname))

        # Download each resource or snap.
        for resource in resources:

            # Create the filename from the snap Name and Path extension. Use this instead of just Path because
            # multiple resources can have the same names for Paths.
            extension = os.path.splitext(resource['Path'])[1]
            filename = resource['Name'] + extension;

            print('    Downloading resource %s...' % filename)

            path = os.path.join(root, 'resources', appname, filename)

            # If it's a snap, download it from the store.
            if resource['Path'].endswith('.snap'):
                channel = 'stable'

                # Try to get channel from bundle
                if 'Options' in app:
                    if 'channel' in app['Options']:
                        channel = app['Options']['channel']

                # Try to get channel from config
                with open(os.path.join(root, 'charms', appname, 'config.yaml'), 'r') as stream:
                    config = yaml.load(stream)
                    if 'options' in config:
                        if 'channel' in config['options']:
                            channel = config['options']['channel']['default'] # Might need to check if this is nonsensical

                # Path without .snap extension is currently a match for the name in the snap store. This may not always
                # be the case.
                snap = resource['Path'].replace('.snap', '')

                # Download the snap and move it into position.
                check_output(('snap download %s --channel=stable' % snap).split(), stderr=STDOUT)
                check_call('rm *.assert', shell=True)
                check_call('mv %s* %s' % (snap, path), shell=True)

            # This isn't a snap, do it the easy way.
            else:
                url = 'https://api.jujucharms.com/charmstore/v5/%s/resource/%s/%d' % (id, resource['Name'], resource['Revision'])
                check_call(('wget --quiet %s -O %s' % (url, path)).split())

            # Store a juju command for attaching the resource.
            attachcmds.append('juju attach %s %s=%s' % (appname, resource['Name'], os.path.join('.', 'resources', appname, filename)))

    # Store juju commands for relating charms.
    for relation in bundle['Relations']:
        relatecmds.append('juju relate %s %s' % (relation[0], relation[1]))

    # Write the deployment script.
    shpath = os.path.join(root, 'deploy.sh')
    with open(shpath, 'w') as sh:
        sh.write('#!/bin/bash\n\n')
        sh.write('set -eux\n\n')
        for cmd in deploycmds:
            sh.write(cmd + '\n')
        for cmd in attachcmds:
            sh.write(cmd + '\n')
        for cmd in relatecmds:
            sh.write(cmd + '\n')

    # Make the deployment script executable.
    st = os.stat(shpath)
    os.chmod(shpath, st.st_mode | stat.S_IEXEC)

    # Make the tarball.
    check_call(('tar -czf %s.tar.gz %s' % (root, root)), shell=True)
    shutil.rmtree(root)

    print('Done.')


if __name__ == '__main__':
    main()
