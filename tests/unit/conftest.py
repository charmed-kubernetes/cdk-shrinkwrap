from pathlib import Path
from types import SimpleNamespace

from jinja2 import FileSystemLoader, Environment
import pytest

DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(params=["applications", "services"])
def test_bundle(request, tmpdir):
    templateEnv = Environment(loader=FileSystemLoader(searchpath=DATA))
    template = templateEnv.get_template("test_bundle.yaml")

    rendered = tmpdir / "test_bundle.yaml"
    with open(rendered, "w") as f:
        f.write(template.render({"apps_or_svcs": request.param}))
    yield SimpleNamespace(file=rendered, apps=request.param)


@pytest.fixture
def test_overlay():
    yield DATA / "test_overlay.yaml"


@pytest.fixture
def test_container_listing():
    yield DATA / "test_container_listing.txt"


@pytest.fixture
def test_charm_config():
    yield DATA / "test_charm_config.yaml"
