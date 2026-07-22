import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture
def registries():
    """Snapshot/restore the accountant's global registries around a test."""
    from euthyna.core import accountant

    schemas = copy.deepcopy(accountant.PROVIDER_CACHE_SCHEMAS)
    sheet = copy.deepcopy(accountant.PRICE_SHEET)
    yield
    accountant.PROVIDER_CACHE_SCHEMAS.clear()
    accountant.PROVIDER_CACHE_SCHEMAS.update(schemas)
    accountant.PRICE_SHEET.clear()
    accountant.PRICE_SHEET.update(sheet)
