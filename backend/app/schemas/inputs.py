from datetime import date
from typing import Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic.alias_generators import to_camel

from app.core.config import settings
from app.models.enums import CaseStatus, PolicyStatus, Priority, Role



def _valid_email(value: str) -> str:
    """Syntax check only. Reserved domains (.local, .test) are accepted outside production so demo accounts work."""
    try:
        return validate_email(value, check_deliverability=False, test_environment=not settings.is_production).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(str(exc))


EmailStr = Annotated[str, AfterValidator(_valid_email)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


class In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class RegisterIn(In):
    full_name: Name
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str
    organization_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)] | None = None


class AcceptInviteIn(In):
    token: str = Field(min_length=20, max_length=200)
    full_name: Name
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str


class LoginIn(In):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordIn(In):
    email: EmailStr


class ResetPasswordIn(In):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str


class ChangePasswordIn(In):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class ProfileUpdateIn(In):
    full_name: Name | None = None
    email: EmailStr | None = None
    avatar_url: Annotated[str, StringConstraints(max_length=500)] | None = None

    @field_validator("avatar_url")
    @classmethod
    def _url(cls, v):
        if v and not v.lower().startswith(("https://", "http://")):
            raise ValueError("Profile picture must be an http(s) URL")
        return v or None


class OrganizationUpdateIn(In):
    name: Name


class InviteIn(In):
    email: EmailStr
    role: Role


class UserPatchIn(In):
    role: Role | None = None
    is_active: bool | None = None


class CaseCreateIn(In):
    patient_reference: ShortText
    condition: ShortText
    requested_procedure: ShortText
    priority: Priority = Priority.MEDIUM
    member_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    requested_on: date | None = None


class CaseUpdateIn(In):
    patient_reference: ShortText | None = None
    condition: ShortText | None = None
    requested_procedure: ShortText | None = None
    priority: Priority | None = None
    status: CaseStatus | None = None


class AssignIn(In):
    user_id: str | None = None


class ReviewIn(In):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    expected_version: int | None = None


class RuleIn(In):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=20)]
    name: ShortText
    requirement: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
    fact_name: Literal["physiotherapy_duration", "diagnosis", "mri_report_age_months"]
    operator: Literal[">=", ">", "<=", "<", "==", "contains", "consistent"]
    threshold: Annotated[str, StringConstraints(max_length=80)] | None = None
    unit: Annotated[str, StringConstraints(max_length=30)] | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    expected_evidence: Annotated[str, StringConstraints(max_length=200)] | None = None
    suggested_action: Annotated[str, StringConstraints(max_length=300)] | None = None
    finding_title: Annotated[str, StringConstraints(max_length=200)] | None = None


class PolicyCreateIn(In):
    name: ShortText
    version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    status: PolicyStatus = PolicyStatus.DRAFT
    rules: list[RuleIn] = Field(default_factory=list, max_length=50)


class PolicyPatchIn(In):
    name: ShortText | None = None
    version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)] | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    status: PolicyStatus | None = None
    rules: list[RuleIn] | None = Field(default=None, max_length=50)
