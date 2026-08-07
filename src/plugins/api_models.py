"""Pydantic request/response models for the typed FastAPI routes.

These give the admin tenancy/RBAC endpoints and the tool-call endpoint real
request validation and a documented schema in the auto-generated OpenAPI (/docs).
Response shapes intentionally mirror the original hand-built handlers so behavior
and existing clients/tests are unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --- Organizations ---------------------------------------------------------
class OrgCreate(BaseModel):
    org_id: str = Field(..., min_length=1, description="Unique organization id")
    name: str = Field(..., min_length=1, description="Human-readable org name")
    settings: Optional[dict] = Field(None, description="Opaque per-org settings")


class OrgOut(BaseModel):
    org_id: str
    name: str
    status: str
    created_at: float


# --- Workspaces ------------------------------------------------------------
class WorkspaceCreate(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


class WorkspaceOut(BaseModel):
    workspace_id: str
    org_id: str
    name: str
    created_at: float


# --- Memberships / role bindings ------------------------------------------
class MemberBind(BaseModel):
    principal_id: Optional[str] = Field(None, description="Principal id; or supply 'subject'")
    subject: Optional[str] = Field(None, description="Alias accepted in place of principal_id")
    role: str = Field(..., min_length=1)
    workspace_id: Optional[str] = None

    def resolved_principal(self) -> str:
        return (self.principal_id or self.subject or "").strip()


class MemberOut(BaseModel):
    principal_id: str
    org_id: str
    role: str
    workspace_id: Optional[str] = None


# --- Tool access grants ----------------------------------------------------
class ToolGrantCreate(BaseModel):
    scope_type: str = Field("org", description="principal | org | workspace | role")
    scope_id: Optional[str] = Field(None, description="Defaults to the path org when omitted")
    effect: str = Field("allow", description="allow | deny")
    match_type: str = Field("exact", description="name | tag | owner | all (or exact/prefix/glob)")
    match_value: str = Field(..., min_length=1)


class ToolGrantOut(BaseModel):
    id: Optional[Any] = None
    scope_type: str
    scope_id: str
    effect: str
    match_type: str
    match_value: str
    created_at: float


# --- Tool onboarding -------------------------------------------------------
class OnboardRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Tool name")
    source: str = Field(..., description="Python source for the tool module")
    requirements: List[str] = Field(default_factory=list, description="pip requirements")
    overwrite: bool = Field(False, description="Replace an existing tool of the same name")
    auto_heal: bool = Field(True, description="Attempt auto-fixes on validation errors")


class ValidateSourceRequest(BaseModel):
    source: str = Field(..., description="Python source to validate (not installed)")
    requirements: List[str] = Field(default_factory=list)
    name: Optional[str] = None


class AcceptProposalRequest(BaseModel):
    name: str = Field(..., min_length=1)
    source: str = Field(...)
    requirements: List[str] = Field(default_factory=list)
    overwrite: bool = True


# --- Tool execution --------------------------------------------------------
class ToolCallRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments object")


class ToolCallResult(BaseModel):
    tool: str
    is_error: bool
    structured_content: Optional[Any] = None
    content: List[Any] = Field(default_factory=list)
