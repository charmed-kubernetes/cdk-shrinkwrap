from shrinkwrap import Downloader
from pathlib import Path


def test_downloader():
    downloader = Downloader("/tmp")
    assert str(downloader.path) == "/tmp"
    target = Path("./target")
    assert downloader.args(target) == ("", target)
    assert downloader.args(target, "testable") == (
        " --channel=testable",
        target / "testable",
    )
    assert downloader.args(target, "testable", "ppc") == (
        " --channel=testable --architecture=ppc",
        target / "testable" / "ppc",
    )
