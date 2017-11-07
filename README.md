# cdk-shrinkwrap

Builds a tarball of charms, resources, snaps, and a deploy script for offline installs.

Please see [this wiki page](https://github.com/juju-solutions/bundle-canonical-kubernetes/wiki/Running-CDK-in-a-restricted-environment#install-cdk-using-cdk-shrinkwrap) for documentation.

## Limitations

- Can't build cross-platform tarballs. If you want a tarball for s390x, you'll need to
build it on s390x.
- juju add-unit is going to fail because each new node needs to have the core snap copied over and installed.
- If the machine numbers aren't 0,1,2,3... things are gonna break.

## TODO

- Write an add-unit script that handles adding a machine, installing the core snap, and adding a unit of X to that machine.
- Handle machine numbers better, and don't forget about the add-unit script.
