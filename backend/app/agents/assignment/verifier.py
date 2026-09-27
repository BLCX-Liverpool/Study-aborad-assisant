from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.assignment import AssignmentAnalysis, AssignmentRequirement


class VerificationStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class VerificationFinding(BaseModel):
    status: VerificationStatus
    message: str
    field: str | None = None


class AssignmentVerificationResult(BaseModel):
    status: VerificationStatus
    findings: list[VerificationFinding] = Field(default_factory=list)


class AssignmentVerifier:
    def verify(self, analysis: AssignmentAnalysis) -> AssignmentVerificationResult:
        findings: list[VerificationFinding] = []

        if not analysis.objective.strip():
            findings.append(
                VerificationFinding(
                    status=VerificationStatus.FAILED,
                    field="objective",
                    message="Assignment objective is missing.",
                )
            )

        if analysis.deadline is not None:
            deadline_requirements = [
                requirement
                for requirement in analysis.marking_criteria + analysis.constraints
                if requirement.requirement_type == "deadline"
            ]
            if not any(_has_evidence(requirement) for requirement in deadline_requirements):
                findings.append(
                    VerificationFinding(
                        status=VerificationStatus.WARNING,
                        field="deadline",
                        message="Deadline exists but no deadline requirement with evidence was found.",
                    )
                )

        for index, requirement in enumerate(analysis.marking_criteria):
            if not _has_evidence(requirement):
                findings.append(
                    VerificationFinding(
                        status=VerificationStatus.WARNING,
                        field=f"marking_criteria[{index}]",
                        message="Marking criterion has no evidence.",
                    )
                )

        for index, requirement in enumerate(analysis.constraints):
            if not _has_evidence(requirement):
                findings.append(
                    VerificationFinding(
                        status=VerificationStatus.WARNING,
                        field=f"constraints[{index}]",
                        message="Constraint has no evidence.",
                    )
                )

        status = VerificationStatus.PASSED
        if any(finding.status == VerificationStatus.FAILED for finding in findings):
            status = VerificationStatus.FAILED
        elif findings:
            status = VerificationStatus.WARNING

        return AssignmentVerificationResult(status=status, findings=findings)


def _has_evidence(requirement: AssignmentRequirement) -> bool:
    return any(
        evidence.source_file_id
        and (evidence.page is not None or evidence.slide is not None or evidence.section)
        for evidence in requirement.evidence
    )

