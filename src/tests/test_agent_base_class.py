import pytest
from agentic_configuration_service.apis import default_api


async def launch_and_execute_agent(agent_id:int, launch_info:dict, user_info:dict):
    await default_api.launch_agent(
        id=agent_id,
        user_info=launch_info
    )
    await default_api.execute_agent(
        id=agent_id,
        user_info=user_info
    )
