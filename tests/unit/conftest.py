from tempfile import TemporaryDirectory
import pytest


@pytest.fixture()
def tmp_dir():
    with TemporaryDirectory() as tp:
        yield tp
