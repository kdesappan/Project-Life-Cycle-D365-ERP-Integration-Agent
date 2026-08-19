from enum import Enum
from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    POSTING = "posting"
    POSTED = "posted"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"


class SessionStatus(str, Enum):
    CREATED = "created"
    EXTRACTING = "extracting"
    AWAITING_APPROVAL = "awaiting_approval"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


PROCESS_STEPS = [
    {
        "id": "reference_data",
        "order": 1,
        "name": "Prerequisite Master & Reference Data",
        "description": "Legal entity, customer, payment terms, VAT group, project group",
        "payload_file": "00_reference_data.json",
        "d365_entities": ["LegalEntities", "CustomersV3", "PaymentTerms", "TaxGroups", "ProjectGroups"],
        "icon": "🏛️",
    },
    {
        "id": "project_contract",
        "order": 2,
        "name": "Project Contract",
        "description": "Contract header, funding source, funding rule and legal terms",
        "payload_file": "01_project_contract.json",
        "d365_entities": ["ProjectContractHeaders", "ProjectContractFundingSources", "ProjectContractFundingRules"],
        "icon": "📄",
    },
    {
        "id": "project_master",
        "order": 3,
        "name": "Project Master Hierarchy",
        "description": "Parent project and sub-projects per performance obligation",
        "payload_file": "02_project_master.json",
        "d365_entities": ["ProjectsV2"],
        "icon": "🗂️",
    },
    {
        "id": "ifrs15_obligations",
        "order": 4,
        "name": "IFRS 15 Performance Obligations",
        "description": "Performance obligations with SSP allocation carried on sub-project records",
        "payload_file": "03_ifrs15_performance_obligations.json",
        "d365_entities": ["Projects"],
        "icon": "⚖️",
    },
    {
        "id": "milestone_billing",
        "order": 5,
        "name": "Milestone Billing Schedule",
        "description": "Milestone dates, acceptance criteria, value split by POB and VAT",
        "payload_file": "04_milestone_billing_schedule.json",
        "d365_entities": ["ProjectOnAccForecasts"],
        "icon": "📅",
    },
    {
        "id": "invoice_schedule",
        "order": 6,
        "name": "Invoice Schedule",
        "description": "On-account invoice proposals with per-POB lines, VAT and due dates",
        "payload_file": "05_invoice_schedule.json",
        "d365_entities": ["ProjectInvoiceProposalHeaders", "ProjectInvoiceProposalOnAccountLines"],
        "icon": "🧾",
    },
    {
        "id": "revenue_recognition",
        "order": 7,
        "name": "Revenue Recognition",
        "description": "Revenue recognition schedule handled by D365 automation batch; no separate posting agent required",
        "payload_file": "06_revenue_recognition.json",
        "d365_entities": ["D365 Revenue Recognition Automation Batch"],
        "icon": "📊",
    },
]

STEP_ID_TO_META = {s["id"]: s for s in PROCESS_STEPS}


class D365CallResult(BaseModel):
    entity: str
    method: str
    path: str
    status_code: Optional[int] = None
    success: bool = False
    response_body: Optional[dict] = None
    error: Optional[str] = None
    executed_at: Optional[datetime] = None


class ProcessStep(BaseModel):
    id: str
    order: int
    name: str
    description: str
    payload_file: str
    d365_entities: list[str]
    icon: str
    status: StepStatus = StepStatus.PENDING
    extracted_payload: Optional[dict] = None
    d365_calls: list[D365CallResult] = Field(default_factory=list)
    approval_note: Optional[str] = None
    rejection_reason: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Session(BaseModel):
    session_id: str
    filename: str
    file_path: str
    status: SessionStatus = SessionStatus.CREATED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    steps: list[ProcessStep] = Field(default_factory=list)
    extraction_error: Optional[str] = None
    d365_environment: Optional[str] = None
    data_area_id: str = "2020"

    def get_step(self, step_id: str) -> Optional[ProcessStep]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    message: str


class ApprovalRequest(BaseModel):
    note: Optional[str] = None


class RejectionRequest(BaseModel):
    reason: str


class D365Settings(BaseModel):
    base_url: str
    tenant_id: str
    client_id: str
    client_secret: str
    data_area_id: str = "2020"
