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
    deploy.append("until [[ %d =~ `juju machines | grep started | wc -l` ]]; do sleep 1; echo Waiting for machines to start...; done" % machineCount) # noqa
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

    # Keep track of subordinate applications.
    subordinates = []

    # For each application, download the charm, resources, and snaps.
    for appname, app in bundle['applications'].items():
        print(appname)

        # Get the charm ID without cs: prepended.
        id = app['Charm'][3:]

        # Download the charm and unzip it.
        print('    Downloading %s...' % id)
        check_call(('wget --quiet https://api.jujucharms.com/charmstore/v5/%s/archive -O /tmp/archive.zip' % id).split())
        check_call(('unzip -qq /tmp/archive.zip -d %s/charms/%s' % (root, appname)).split())
        check_call('rm /tmp/archive.zip'.split())

        # If this is a subordinate charm, we won't need a machine for it.
        with open(os.path.join(root, 'charms', appname, 'metadata.yaml'), 'r') as stream:
            metadata = yaml.load(stream)
            if 'subordinate' in metadata and metadata['subordinate'] is True:
                subordinates.append(appname)

        # Get the charm resources metadata.
        resp = requests.get('https://api.jujucharms.com/charmstore/v5/%s/meta/resources' % id)
        resources = json.loads(resp.text)
        bundle['applications'][appname]['resources'] = resources

        # Create a path to store the charm resources.
        os.makedirs(os.path.join(root, 'resources', appname))

        # Download each resource or snap.
        for resource in resources:

            # Create the filename from the snap Name and Path extension. Use this instead of just Path because
            # multiple resources can have the same names for Paths.
            extension = os.path.splitext(resource['Path'])[1]
            filename = resource['Name'] + extension
            resource['filename'] = filename

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
                            # Might need to check if this is nonsensical
                            channel = config['options']['channel']['default']

                # Path without .snap extension is currently a match for the name in the snap store. This may not always
                # be the case.
                snap = resource['Path'].replace('.snap', '')

                # Download the snap and move it into position.
                check_output(('snap download %s --channel=%s' % (snap, channel)).split(), stderr=STDOUT)
                check_call('rm *.assert', shell=True)
                check_call('mv %s* %s' % (snap, path), shell=True)

            # This isn't a snap, do it the easy way.
            else:
                url = 'https://api.jujucharms.com/charmstore/v5/%s/resource/%s/%d' % (id,
                                                                                      resource['Name'],
                                                                                      resource['Revision'])
                check_call(('wget --quiet %s -O %s' % (url, path)).split())

    print('Writing deploy scripts...')
    build_deploy_script(os.path.join(root, 'deploy.sh'), bundle, subordinates)
    print('    deploy.sh')
    for appname, app in bundle['applications'].items():
        script_filename = os.path.join(root, 'add-unit-{}.sh'.format(appname))
        app_to_deploy = {appname: app}
        build_deploy_script(script_filename, bundle, subordinates, app_to_deploy)
        print('    {}'.format(script_filename))

    # Download the core snap.
    print('Downloading the core snap...')
    check_output('snap download core --channel=stable'.split(), stderr=STDOUT)
    check_call('mv core*.snap %s' % os.path.join(root, 'resources', 'core.snap'), shell=True)
    check_call('rm *.assert', shell=True)

    # Make the tarball.
    check_call(('tar -czf %s.tar.gz %s' % (root, root)), shell=True)
    shutil.rmtree(root)

    print('Done.')


if __name__ == '__main__':
    main()
