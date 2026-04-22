"""State shared between agent and frontend via AG-UI."""
from pydantic import BaseModel, Field

class PotpieState(BaseModel):
    project_id: str | None = Field(default=None, description="Active project ID")
    agent_id: str | None = Field(default="codebase_qna_agent", description="Active agent type")
    last_response: str | None = Field(default=None, description="Last agent response")
    projects: list[dict] = Field(default_factory=list, description="Cached project list")
