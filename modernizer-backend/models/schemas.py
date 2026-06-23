from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class PatternType(str, Enum):
    JAVA17_TO_JAVA25 = "java17-to-java25"
    JAVA_TO_GO = "java-to-go"
    JAVA_TO_QUARKUS = "java-to-quarkus"
    TIBCO_TO_SPRINGBOOT = "tibco-to-springboot"


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


class ConfirmRequest(BaseModel):
    feedback: Optional[str] = None
    content: Optional[str] = None               # edited BRD text
    technical_spec_content: Optional[str] = None  # edited Technical Specification text


class SessionInfo(BaseModel):
    session_id: str
    pattern: PatternType
    status: SessionStatus
    brd: Optional[str] = None
    plan: Optional[str] = None
    generated_files: Optional[List[GeneratedFile]] = None
