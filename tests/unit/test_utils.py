from pathlib import Path

import yaml

from shrinkwrap import charm_channel, _remove_prefix, _remove_suffix


def test_remove_prefix():
    assert _remove_prefix("something-abc", "something") == "-abc"
    assert _remove_prefix("abc", "something") == "abc"
    assert _remove_prefix("abc-something", "something") == "abc-something"


def test_remove_suffix():
    assert _remove_suffix("something-abc", "something") == "something-abc"
    assert _remove_suffix("abc", "something") == "abc"
    assert _remove_suffix("abc-something", "something") == "abc-"


def test_charm_channel(tmp_dir):
    charm_path = Path(tmp_dir) / "charm" / "etcd"
    charm_path.mkdir(parents=True)
    with (Path(__file__).parent / "test_charm_config.yaml").open() as fp:
        (charm_path / "config.yaml").write_text(fp.read())
    with (Path(__file__).parent / "test_bundle.yaml").open() as fp:
        bundle = yaml.safe_load(fp)
    etcd = bundle["applications"]["etcd"]

    assert charm_channel(etcd, charm_path) == "3.4/stable"
