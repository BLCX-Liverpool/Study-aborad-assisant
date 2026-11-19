from dataclasses import dataclass


COMMAND_EXCHANGE = "study.agent.commands.v1"
EVENT_EXCHANGE = "study.agent.events.v1"
DEAD_LETTER_EXCHANGE = "study.agent.dlx.v1"


@dataclass(frozen=True)
class QueueSpec:
    name: str
    exchange: str
    routing_keys: tuple[str, ...]
    prefetch: int


QUEUE_SPECS: tuple[QueueSpec, ...] = (
    QueueSpec("study.workflow.prepare.q", COMMAND_EXCHANGE, ("workflow.prepare",), 20),
    QueueSpec("study.assignment.q", COMMAND_EXCHANGE, ("agent.task.assignment",), 1),
    QueueSpec("study.travel.q", COMMAND_EXCHANGE, ("agent.task.travel",), 4),
    QueueSpec("study.finance.q", COMMAND_EXCHANGE, ("agent.task.finance",), 4),
    QueueSpec("study.fitness.q", COMMAND_EXCHANGE, ("agent.task.fitness",), 4),
    QueueSpec("study.planner.q", COMMAND_EXCHANGE, ("agent.task.planner",), 4),
    QueueSpec("study.email.q", COMMAND_EXCHANGE, ("agent.task.email",), 2),
    QueueSpec("study.notice.q", COMMAND_EXCHANGE, ("agent.task.notice",), 4),
    QueueSpec("study.social.q", COMMAND_EXCHANGE, ("agent.task.social",), 4),
    QueueSpec("study.wellbeing.q", COMMAND_EXCHANGE, ("agent.task.wellbeing",), 4),
    QueueSpec("study.orchestrator.events.q", EVENT_EXCHANGE, ("agent.step.*", "artifact.created", "workflow.completed"), 20),
    QueueSpec("study.dead.q", DEAD_LETTER_EXCHANGE, ("#",), 20),
)


ROUTING_KEY_BY_AGENT = {
    "assignment": "agent.task.assignment",
    "travel": "agent.task.travel",
    "finance": "agent.task.finance",
    "fitness": "agent.task.fitness",
    "task_planning": "agent.task.planner",
    "email": "agent.task.email",
    "email_send": "agent.task.email",
    "notice_action": "agent.task.notice",
    "social_content": "agent.task.social",
    "wellbeing": "agent.task.wellbeing",
}


def queue_spec(name: str) -> QueueSpec:
    for spec in QUEUE_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(f"Unknown RabbitMQ queue: {name}")
