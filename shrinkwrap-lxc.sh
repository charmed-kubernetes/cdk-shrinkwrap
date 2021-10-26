#!/bin/bash

# LXC Requires privileged to run docker daemon
lxc launch ubuntu:20.04 shrinkwrap -c security.privileged=true
lxc file push ./requirements.txt shrinkwrap/root/
lxc file push ./shrinkwrap.py shrinkwrap/root/
lxc file push -p -r ./templates shrinkwrap/root/
sleep 2

function dependencies {
  lxc exec shrinkwrap -- apt update
  lxc exec shrinkwrap -- apt install -y python3-pip unzip docker.io
  lxc exec shrinkwrap -- pip install -r /root/requirements.txt
  lxc exec shrinkwrap -- snap install juju --classic
  lxc exec shrinkwrap -- snap install snap-store-proxy
}

dependencies
lxc exec shrinkwrap -- /root/shrinkwrap.py $@
lxc file pull -p -r 'shrinkwrap/root/build/' .

echo '# on success -- delete the container'
echo 'lxc stop shrinkwrap && lxc rm shrinkwrap'