# cdk-shrinkwrap

Builds a tarball of charms, resources, snaps, and a deploy script for offline installs.

Please see [this wiki page][wiki-page] for documentation.

## Limitations

- Can't build cross-platform tarballs. If you want a tarball for s390x, you'll need to build it on s390x.
- juju add-unit without a --to directive is going to fail because each new node needs to have the core snap 
  copied over and installed.

## TODO

- Placement directives in the bundle aren't currently honored. If the bundle has to: directives in it, 
  the script currently will not generate something to match that.


## Dependencies
### PIP Packages

- `requests`
- `pyyaml`
- `semver`


### Necessary Snaps 

- `juju`
- `docker`

[wiki-page]: https://github.com/juju-solutions/bundle-canonical-kubernetes/wiki/Running-CDK-in-a-restricted-environment#install-cdk-using-cdk-shrinkwrap