import pytest
from ..tools import azure_intelligence_summary
from .test_agent_base_class import launch_and_execute_agent


def test_azure_intelligence_summary():
    response = azure_intelligence_summary.azure_intelligence_summary(file_path="ArtamneOuLeGrandCyrusSixiimePartie.pdf")


async def test_launch_and_execute_azure_intelligence_summary_agent():
    await launch_and_execute_agent(agent_id=229,
                                   launch_info={},
                                   user_info={}
                                   )
