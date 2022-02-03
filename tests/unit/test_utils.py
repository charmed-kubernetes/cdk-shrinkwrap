from pathlib import Path
import yaml

from shrinkwrap import remove_suffix, remove_prefix, charm_channel


def test_remove_prefix():
    assert remove_prefix("something-abc", "something") == "-abc"
    assert remove_prefix("abc", "something") == "abc"
    assert remove_prefix("abc-something", "something") == "abc-something"


def test_remove_suffix():
    assert remove_suffix("something-abc", "something") == "something-abc"
    assert remove_suffix("abc", "something") == "abc"
    assert remove_suffix("abc-something", "something") == "abc-"


def test_charm_channel(tmpdir, test_charm_config, test_bundle):
    charm_path = Path(tmpdir) / "charm" / "etcd"
    charm_path.mkdir(parents=True)
    with test_charm_config.open() as fp:
        (charm_path / "config.yaml").write_text(fp.read())
    with test_bundle.file.open() as fp:
        bundle = yaml.safe_load(fp)
    etcd = bundle[test_bundle.apps]["etcd"]

    assert charm_channel(etcd, charm_path) == "3.4/stable"
