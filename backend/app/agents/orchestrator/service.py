from app.agents.orchestrator.graph import build_orchestrator_graph
from app.agents.orchestrator.repository import AgentRunRecorder, RouterObservationRepository, TraceSpanRepository
from app.agents.orchestrator.workers import WorkerRegistry
from app.agents.router.service import IntentRouter
from app.memory.manager import MemoryManager
from app.schemas.chat import ChatRequest, ChatResponse


class StudyAbroadOrchestrator:
    def __init__(
        self,
        router: IntentRouter | None = None,
        recorder: AgentRunRecorder | None = None,
        router_observations: RouterObservationRepository | None = None,
        trace_spans: TraceSpanRepository | None = None,
        memory_manager: MemoryManager | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self.router = router or IntentRouter()
        self.recorder = recorder
        self.router_observations = router_observations
        self.trace_spans = trace_spans
        self.memory_manager = memory_manager or MemoryManager()
        self.worker_registry = worker_registry or WorkerRegistry()

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        graph = build_orchestrator_graph(
            router=self.router,
            memory_manager=self.memory_manager,
            worker_registry=self.worker_registry,
            recorder=self.recorder,
            router_observations=self.router_observations,
            trace_spans=self.trace_spans,
        )
        result = await graph.ainvoke({"request": request})
        return result["response"]
