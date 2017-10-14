#!/usr/bin/env python3

import os
import argparse
import json
import yaml
import requests
import tempfile
import stat
import shutil
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
    resp = requests.get('https://api.jujucharms.com/charmstore/v5/meta/bundle-metadata',
                        params={'id': args.bundle, 'channel': args.channel})
    bundle = json.loads(resp.text)[args.bundle]
    temp = tempfile.mkdtemp()
    os.makedirs('%s/charms' % temp)
    os.makedirs('%s/resources' % temp)
    deploycmds = []
    attachcmds = []
    relatecmds = []
    for appname, app in bundle['applications'].items():
        print(appname)
        id = app['Charm'][3:]
        print('    Downloading charm...')
        check_call(('wget --quiet https://api.jujucharms.com/charmstore/v5/%s/archive -O /tmp/archive.zip' % id).split())
        check_call(('unzip -qq /tmp/archive.zip -d %s/charms/%s' % (temp, appname)).split())
        check_call('rm /tmp/archive.zip'.split())
        deploycmds.append("juju deploy ./charms/%s" % appname)
        resp = requests.get('https://api.jujucharms.com/charmstore/v5/%s/meta/resources' % id)
        resources = json.loads(resp.text)
        os.makedirs(os.path.join(temp, 'resources', appname))
        for resource in resources:
            extension = os.path.splitext(resource['Path'])[1]
            filename = resource['Name'] + extension;
            print('    Downloading resource %s...' % filename)
            path = os.path.join(temp, 'resources', appname, filename)
            if resource['Path'].endswith('.snap'):
                channel = 'stable'
                # Try to get channel from bundle
                if 'Options' in app:
                    if 'channel' in app['Options']:
                        channel = app['Options']['channel']
                # Try to get channel from config
                with open(os.path.join(temp, 'charms', appname, 'config.yaml'), 'r') as stream:
                    config = yaml.load(stream)
                    if 'options' in config:
                        if 'channel' in config['options']:
                            channel = config['options']['channel']['default'] # Might need to check if this is nonsensical
                snap = resource['Path'].replace('.snap', '')
                check_output(('snap download %s --channel=stable' % snap).split(), stderr=STDOUT)
                check_call('rm *.assert', shell=True)
                check_call('mv %s* %s' % (snap, path), shell=True)
            else:
                url = 'https://api.jujucharms.com/charmstore/v5/%s/resource/%s/%d' % (id, resource['Name'], resource['Revision'])
                check_call(('wget --quiet %s -O %s' % (url, path)).split())
            attachcmds.append('juju attach %s %s=%s' % (appname, resource['Name'], os.path.join('.', 'resources', appname, filename)))
    for relation in bundle['Relations']:
        relatecmds.append('juju relate %s %s' % (relation[0], relation[1]))
    shpath = os.path.join(temp, 'deploy.sh')
    with open(shpath, 'w') as sh:
        sh.write('#!/bin/bash\n\n')
        sh.write('set -eux\n\n')
        for cmd in deploycmds:
            sh.write(cmd + '\n')
        for cmd in attachcmds:
            sh.write(cmd + '\n')
        for cmd in relatecmds:
            sh.write(cmd + '\n')
    st = os.stat(shpath)
    os.chmod(shpath, st.st_mode | stat.S_IEXEC)
    tempname = '/tmp/%s' % args.bundle
    if os.path.isdir(tempname):
        os.path.rmtree(tempname)
    check_call('mv %s %s' % (temp, tempname), shell=True)
    check_call(('cd /tmp && tar -czf %s.tar.gz %s' % (args.bundle, args.bundle)), shell=True)
    check_call('mv /tmp/%s.tar.gz .' % args.bundle, shell=True)
    shutil.rmtree(tempname)
    print('Done.')


if __name__ == '__main__':
    main()
