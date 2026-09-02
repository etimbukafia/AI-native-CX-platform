import os

import pytest

from cx_platform.memory import MemoryScope, SenseLabMemory


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("CX_SENSELAB_LIVE") != "1",
    reason="set CX_SENSELAB_LIVE=1 to run the opt-in SenseLab smoke test",
)
def test_opt_in_senselab_live_search_smoke() -> None:
    memory = SenseLabMemory.from_environment()

    try:
        result = memory.search_relevant(
            execution_id="cx_live_smoke",
            scope=MemoryScope.SHARED_SUPPORT,
            capability_id="delivery_resolution",
            limit=1,
        )
        assert isinstance(result, list)
    finally:
        memory.close()
