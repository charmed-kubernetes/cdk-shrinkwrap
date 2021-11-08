# cdk-shrinkwrap
[![Test Suite](https://github.com/charmed-kubernetes/cdk-shrinkwrap/actions/workflows/main.yml/badge.svg?branch=master)](https://github.com/charmed-kubernetes/cdk-shrinkwrap/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/charmed-kubernetes/cdk-shrinkwrap/branch/master/graph/badge.svg?token=rI9OruOCKk)](https://codecov.io/gh/charmed-kubernetes/cdk-shrinkwrap)


Builds a tarball of charms, resources, containers, snap-store-proxy tarballs, and a deploy script for offline installs.

Please see [this offline install docs][offline-docs-page] for usage.

## Limitations

- Can't build cross-platform tarballs. If you want a tarball for s390x, you'll need to build it on s390x.
- juju add-unit without a --to directive is going to fail because each new node needs to have the core snap 
  copied over and installed.

## Execution
* the following will generate a lxc container titled 'shrinkwrap' which will install necessary dependants and produce
  help output explaining how to use.  See [offline-docs-page] for more details.
```bash
$ ./shrinkwrap-lxc.sh --help
...
usage: shrinkwrap.py [-h] [--channel CHANNEL] [--arch ARCH] [--use_path USE_PATH] [--overlay OVERLAY] [bundle]

positional arguments:
  bundle                the bundle to shrinkwrap

optional arguments:
  -h, --help            show this help message and exit
  --channel CHANNEL, -c CHANNEL
                        the channel of the bundle
  --arch ARCH, -a ARCH  the target architecture of the bundle
  --use_path USE_PATH, -d USE_PATH
                        Use existing root path.
  --overlay OVERLAY     Set of overlays to apply to the base bundle.
...
```

## Dependencies
### Deb Packages
- python3.8
- docker.io

### PIP Packages

- `requests`
- `pyyaml`
- `semver`
- `jinja2`
- `retry`

### Necessary Snaps 

- `snap-store-proxy`

[offline-docs-page]: https://ubuntu.com/kubernetes/docs/install-offline