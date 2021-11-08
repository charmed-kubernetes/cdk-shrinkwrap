from subprocess import STDOUT

from shrinkwrap import SnapDownloader

import mock
import pytest


@pytest.fixture()
def mock_snap_cmd():
    with mock.patch("shrinkwrap.check_call"):
        with mock.patch("shrinkwrap.check_output") as co:
            yield co


def test_snap_downloader(tmp_dir, mock_snap_cmd):
    downloader = SnapDownloader(tmp_dir)
    assert downloader.empty_snap.exists(), "Empty Snap file doesn't exist"
    mock_snap_cmd.return_value = (
        "Fetching channel map info for jq\n"
        "Downloaded jq to /var/snap/snap-store-proxy/common/downloads/jq-20211019T154844.tar.gz\n"
    )
    snap_path = downloader.mark_download("jq", "latest/stable", None)
    assert snap_path == (" --channel=latest/stable", downloader.path / "jq" / "latest" / "stable")
    assert not snap_path[1].exists()

    downloader.download()
    mock_snap_cmd.assert_called_once_with(
        "snap-store-proxy fetch-snaps jq --channel=latest/stable".split(),
        stderr=STDOUT,
        text=True,
    )
