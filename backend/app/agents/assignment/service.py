from pathlib import Path

from app.agents.assignment.extractor import AssignmentRequirementExtractor
from app.agents.assignment.verifier import AssignmentVerificationResult, AssignmentVerifier
from app.documents.chunking import chunk_document
from app.documents.parser import DoclingDocumentParser
from app.schemas.assignment import AssignmentAnalysis


class AssignmentAnalysisResult:
    def __init__(
        self,
        analysis: AssignmentAnalysis,
        verification: AssignmentVerificationResult,
    ) -> None:
        self.analysis = analysis
        self.verification = verification


class AssignmentAnalysisService:
    def __init__(
        self,
        parser: DoclingDocumentParser,
        extractor: AssignmentRequirementExtractor,
        verifier: AssignmentVerifier,
    ) -> None:
        self.parser = parser
        self.extractor = extractor
        self.verifier = verifier

    async def analyze_file(
        self,
        source_path: Path,
        file_id: str,
        source_name: str | None = None,
        mime_type: str | None = None,
    ) -> AssignmentAnalysisResult:
        parsed_document = self.parser.parse(
            source_path=source_path,
            file_id=file_id,
            source_name=source_name,
            mime_type=mime_type,
        )
        chunks = chunk_document(parsed_document)
        analysis = await self.extractor.extract(chunks)
        verification = self.verifier.verify(analysis)
        return AssignmentAnalysisResult(analysis=analysis, verification=verification)

