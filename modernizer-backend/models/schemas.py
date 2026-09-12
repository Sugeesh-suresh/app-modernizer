from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class PatternType(str, Enum):
    JAVA_8_TO_25 = "java-8-to-25"
    SOLR_4_TO_9 = "solr-4-to-9"
    ORACLE_19C_TO_23AI = "oracle-19c-to-23ai"
    TIBCO_EMS_TO_PUBSUB = "tibco-ems-to-pubsub"
    JSP_TO_REACT_BFF = "jsp-to-react-bff"


class MigrationStrategy(str, Enum):
    BIGBANG = "bigbang"
    INCREMENTAL = "incremental"


class SessionStatus(str, Enum):
    UPLOADING = "uploading"
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
    # Number of UX design files attached (JSP -> React only)
    ux_designs: int = 0


class ConfirmRequest(BaseModel):
    feedback: Optional[str] = None
    content: Optional[str] = None               # edited BRD text
    technical_spec_content: Optional[str] = None  # edited Technical Specification text


class RefineRequest(BaseModel):
    feedback: str


class SelectCompanionsRequest(BaseModel):
    selected: List[str] = []


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
