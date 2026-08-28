from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.path).replace("\\", "/")
        if "/unit/" in path and item.get_closest_marker("unit") is None:
            item.add_marker(pytest.mark.unit)
        if "/security/" in path and item.get_closest_marker("security") is None:
            item.add_marker(pytest.mark.security)
        if "/api/" in path and item.get_closest_marker("api") is None:
            item.add_marker(pytest.mark.api)
