from app.agents.finance.bill_parser import FinanceBillParser
from app.agents.finance.bill_verifier import FinanceBillVerifier
from app.agents.finance.budget_goals import BudgetGoalPlanner
from app.agents.finance.budget_analyzer import StudentBudgetAnalyzer
from app.agents.finance.csv_parser import ExpenseCsvParser
from app.documents.parser import DoclingDocumentParser
from app.schemas.finance import (
    BudgetGoalOutput,
    BudgetGoalRequest,
    FinanceBillParseOutput,
    FinanceBillParseRequest,
    FinancePlanOutput,
    FinancePlanRequest,
)


class FinanceAgentService:
    def __init__(
        self,
        csv_parser: ExpenseCsvParser | None = None,
        analyzer: StudentBudgetAnalyzer | None = None,
        bill_parser: FinanceBillParser | None = None,
        bill_verifier: FinanceBillVerifier | None = None,
        goal_planner: BudgetGoalPlanner | None = None,
        document_parser: DoclingDocumentParser | None = None,
    ) -> None:
        self.csv_parser = csv_parser or ExpenseCsvParser()
        self.analyzer = analyzer or StudentBudgetAnalyzer()
        self.bill_parser = bill_parser or FinanceBillParser()
        self.bill_verifier = bill_verifier or FinanceBillVerifier()
        self.goal_planner = goal_planner or BudgetGoalPlanner()
        self.document_parser = document_parser or DoclingDocumentParser()

    def plan_budget(self, request: FinancePlanRequest) -> FinancePlanOutput:
        parsed_expenses = []
        if request.expense_csv:
            parsed_expenses = self.csv_parser.parse(request.expense_csv, request.currency)
        return self.analyzer.analyze(request, parsed_expenses)

    def parse_bill(self, request: FinanceBillParseRequest) -> FinanceBillParseOutput:
        if request.source_path is not None and not request.raw_text.strip():
            parsed = self.document_parser.parse(
                source_path=request.source_path,
                file_id=f"finance_bill:{request.source_path.name}",
                source_name=request.source_name or request.source_path.name,
            )
            request = request.model_copy(
                update={"raw_text": "\n".join(element.text for element in parsed.elements)}
            )
        return self.bill_parser.parse(request)

    async def parse_bill_async(self, request: FinanceBillParseRequest) -> FinanceBillParseOutput:
        output = self.parse_bill(request)
        source_text = request.raw_text
        if not source_text.strip() and output.obligations:
            source_text = "\n".join(obligation.evidence_text for obligation in output.obligations)
        return await self.bill_verifier.verify(output, source_text)

    def review_goals(self, request: BudgetGoalRequest) -> BudgetGoalOutput:
        return self.goal_planner.review(request)
