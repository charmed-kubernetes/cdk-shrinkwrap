#!/bin/bash

lxc launch ubuntu:20.04 shrinkwrap
# Required to run docker daemon in lxc (for a local docker registry)
lxc config set shrinkwrap security.privileged true
lxc file push ./shrinkwrap.py shrinkwrap/root/
lxc file push ./requirements.txt shrinkwrap/root/
sleep 2

function dependencies {
  lxc exec shrinkwrap -- apt update
  lxc exec shrinkwrap -- apt install -y python3-pip unzip docker.io
  lxc exec shrinkwrap -- pip install -r /root/requirements.txt
  lxc exec shrinkwrap -- snap install juju --classic
  lxc exec shrinkwrap -- snap install snap-store-proxy --classic
}

dependencies
lxc exec shrinkwrap -- /root/shrinkwrap.py $@
mkdir -p ./build/
lxc file pull --recursive 'shrinkwrap/root/build/' .

echo '# on success -- delete the container'
echo 'lxc stop shrinkwrap && lxc rm shrinkwrap'