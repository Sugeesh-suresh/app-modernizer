from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class PatternType(str, Enum):
    JAVA_8_TO_25 = "java-8-to-25"
    # JDK-only upgrade: JSP views and the WildFly deployment are frozen.
    JAVA_8_TO_11 = "java-8-to-11"
    SOLR_4_TO_9 = "solr-4-to-9"
    ORACLE_19C_TO_23AI = "oracle-19c-to-23ai"
    TIBCO_EMS_TO_PUBSUB = "tibco-ems-to-pubsub"
    JSP_TO_REACT_BFF = "jsp-to-react-bff"
    # Reverse engineering only: maps the stacks in the repo and documents each
    # one. Produces no plan and no code, so a session on this pattern ends at
    # brd-review rather than passing through plan-review to code-generation.
    STACK_DISCOVERY = "stack-discovery"


class MigrationStrategy(str, Enum):
    BIGBANG = "bigbang"
    INCREMENTAL = "incremental"


class SessionStatus(str, Enum):
    UPLOADING = "uploading"
    STACK_MAPPING = "stack-mapping"  # stack-discovery only
    REVERSE_ENGINEERING = "reverse-engineering"
    BRD_REVIEW = "brd-review"
    PLAN_GENERATION = "plan-generation"
    PLAN_REVIEW = "plan-review"
    CODE_GENERATION = "code-generation"
    COMPLETE = "complete"
    ERROR = "error"


class GeneratedFile(BaseModel):
    path: str
    content: str
    language: str


class UploadResponse(BaseModel):
    session_id: str
    message: str
    files_found: int
    # Files present in the archive that exceeded the server's ingestion limit and
    # were NOT unpacked. Non-zero means every result from this session describes
    # only part of the repository (see main.py's ExtractionResult).
    files_truncated: int = 0
    # Number of UX design files attached (JSP -> React only)
    ux_designs: int = 0
    # False when the analysis is a deterministic inventory passed straight to
    # the planner: the run has no reverse-engineering or analysis-review step.
    analysis_review: bool = True
    # Context files (Swagger, OpenAPI, design docs) accepted with the upload.
    context_files: int = 0
    # True when the run starts with the environment check (JDK, Maven, the
    # uploaded code built on the target JDK) before planning.
    preflight: bool = False


class ConfirmRequest(BaseModel):
    feedback: Optional[str] = None
    content: Optional[str] = None               # edited BRD text
    technical_spec_content: Optional[str] = None  # edited Technical Specification text


class RefineRequest(BaseModel):
    feedback: str
    # stack-discovery only: which writer re-runs — "brd" (Product Owner) or
    # "technical_spec" (Enterprise Architect). Anything else re-runs both.
    target: Optional[str] = None


class SelectCompanionsRequest(BaseModel):
    selected: List[str] = []
    # Stack discovery: render the UI's pages as a "UI Screens" document. Honoured
    # only when the pipeline offered it for this repository.
    screenshots: bool = False
    # Stack discovery: the documents to generate — any of "brd", "technical_spec",
    # "test_inventory", "ui_screens". None keeps the earlier behaviour: the BRD, the
    # Technical Specification and the Test Inventory, and UI Screens when
    # `screenshots` is set. Only what a chosen document needs is run.
    documents: Optional[List[str]] = None


class ChangedFile(BaseModel):
    path: str
    status: str   # "added" | "modified" | "deleted"
    diff: str


class SessionInfo(BaseModel):
    session_id: str
    pattern: PatternType
    status: SessionStatus
    brd: Optional[str] = None
    plan: Optional[str] = None
    generated_files: Optional[List[GeneratedFile]] = None
