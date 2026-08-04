import pytest
from .test_agent_base_class import launch_and_execute_agent


async def test_launch_and_execute_image_gen_agent():
    await launch_and_execute_agent(agent_id=156,
                                   launch_info={},
                                   user_info={}
                                   )
