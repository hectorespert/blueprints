import pathlib
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from homeassistant.components import automation
from homeassistant.components.blueprint import models
from homeassistant.core import callback
from homeassistant.util import yaml as yaml_util

BLUEPRINT_DIR = pathlib.Path(__file__).parent.parent / "blueprints"


@pytest.fixture(autouse=True)
def patch_blueprint_loader() -> Iterator[None]:
    """Load blueprints from this repository during tests."""

    @callback
    def mock_load_blueprint(self, path: str):
        return models.Blueprint(
            yaml_util.load_yaml(BLUEPRINT_DIR / path),  # ty: ignore[invalid-argument-type]
            expected_domain=self.domain,
            path=path,
            schema=automation.config.AUTOMATION_BLUEPRINT_SCHEMA,
        )

    with patch(
        "homeassistant.components.blueprint.models.DomainBlueprints._load_blueprint",
        mock_load_blueprint,
    ):
        yield