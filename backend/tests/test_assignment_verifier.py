from app.agents.assignment.verifier import AssignmentVerifier, VerificationStatus
from app.schemas.assignment import AssignmentAnalysis, AssignmentRequirement
from app.schemas.common import EvidenceRef


def test_verifier_passes_when_requirements_have_evidence() -> None:
    analysis = AssignmentAnalysis(
        objective="Write a report.",
        deliverables=["Report"],
        marking_criteria=[
            AssignmentRequirement(
                requirement_type="marking_criteria",
                content="Structure is worth 20%.",
                evidence=[
                    EvidenceRef(
                        source_file_id="file_1",
                        source_name="brief.pdf",
                        page=3,
                        confidence=0.9,
                    )
                ],
            )
        ],
    )

    result = AssignmentVerifier().verify(analysis)
    assert result.status == VerificationStatus.PASSED


def test_verifier_warns_when_marking_criteria_lack_evidence() -> None:
    analysis = AssignmentAnalysis(
        objective="Write a report.",
        deliverables=["Report"],
        marking_criteria=[
            AssignmentRequirement(
                requirement_type="marking_criteria",
                content="Structure is worth 20%.",
                evidence=[],
            )
        ],
    )

    result = AssignmentVerifier().verify(analysis)
    assert result.status == VerificationStatus.WARNING

