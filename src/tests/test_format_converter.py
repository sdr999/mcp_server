import pytest
from .test_agent_base_class import launch_and_execute_agent


async def test_launch_and_execute_format_converter_agent():
    await launch_and_execute_agent(agent_id=0,
                                   launch_info={},
                                   user_info={}
                                   )
