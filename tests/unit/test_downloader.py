from pathlib import Path

from shrinkwrap import Downloader


def test_downloader(tmp_dir):
    downloader = Downloader(tmp_dir)
    assert str(downloader.path) == tmp_dir
    target = Path("./target")
    assert downloader.to_args(target) == ("", target)
    assert downloader.to_args(target, "testable") == (
        " --channel=testable",
        target / "testable",
    )
    assert downloader.to_args(target, "testable", "ppc") == (
        " --channel=testable --architecture=ppc",
        target / "testable" / "ppc",
    )
