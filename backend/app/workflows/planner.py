from __future__ import annotations

from app.agents.orchestrator.multi_intent_executor import MultiIntentExecutionPlanner
from app.agents.router.service import IntentRouter
from app.memory.manager import MemoryManager
from app.schemas.chat import ChatRequest
from app.schemas.execution import ExecutionStep, MultiIntentExecutionPlan, MultiIntentExecutionRequest
from app.schemas.router import RouterOutput
from app.workflows.repository import WorkflowRepository
from app.workflows.service import WorkflowService
from app.workflows.state_machine import WorkflowStatus


class DurableWorkflowPlanner:
    def __init__(
        self,
        repository: WorkflowRepository,
        *,
        router: IntentRouter | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.repository = repository
        self.router = router or IntentRouter()
        self.memory_manager = memory_manager

    async def prepare(self, workflow_id: str) -> None:
        workflow = await self.repository.get(workflow_id)
        if workflow.status != WorkflowStatus.CREATED.value:
            return
        changed = await self.repository.transition_workflow(workflow, WorkflowStatus.PLANNING)
        if not changed:
            return

        request = ChatRequest.model_validate(workflow.input_json["chat_request"])
        router_json = workflow.input_json.get("router_output")
        # The API persists its synchronous safety/policy route so the durable
        # orchestrator can reuse it as the initial route without a duplicate
        # model call. Planning and dispatch still happen only in this runtime.
        router_output = (
            RouterOutput.model_validate(router_json)
            if router_json
            else await self.router.route_async(
                request.message,
                uploaded_file_ids=request.uploaded_file_ids,
                agent_inputs=request.agent_inputs,
                conversation_context=request.history,
            )
        )
        memory_context = None
        if self.memory_manager is not None:
            memory_context = await self.memory_manager.build_context(
                request=request,
                conversation_id=workflow.conversation_id,
                router_output=router_output,
            )
            # Match the synchronous LangGraph path: a context-resolved query
            # must be routed again before the execution plan is materialized.
            if memory_context.query_rewrite.changed:
                router_output = await self.router.route_async(
                    memory_context.query_rewrite.rewritten_query,
                    uploaded_file_ids=request.uploaded_file_ids,
                    agent_inputs=request.agent_inputs,
                    conversation_context=memory_context.prompt_context,
                )
                memory_context = await self.memory_manager.rebuild_context_after_reroute(
                    request=request,
                    router_output=router_output,
                    memory_context=memory_context,
                )
        plan = _execution_plan(request, router_output)
        workflow.plan_json = {
            "router": router_output.model_dump(mode="json"),
            "execution_plan": plan.model_dump(mode="json"),
            "memory_context": memory_context.model_dump(mode="json") if memory_context else None,
        }
        await self.repository.create_steps(
            workflow.id,
            [step.model_dump(mode="json") for step in plan.steps],
        )
        steps = await self.repository.list_steps(workflow.id)
        if any(step.status == "needs_input" for step in steps):
            await self.repository.transition_workflow(workflow, WorkflowStatus.WAITING_INPUT)
        elif not steps:
            workflow.final_response = "当前请求没有生成可执行步骤。"
            await self.repository.transition_workflow(workflow, WorkflowStatus.COMPLETED)
        else:
            await self.repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
            await WorkflowService(self.repository.session).queue_ready_steps(workflow)


def _execution_plan(request: ChatRequest, router_output: RouterOutput) -> MultiIntentExecutionPlan:
    if len(router_output.structured_intents) > 1:
        return MultiIntentExecutionPlanner().plan(
            MultiIntentExecutionRequest(
                user_id=request.user_id,
                message=request.message,
                structured_intents=router_output.structured_intents,
                agent_inputs=request.agent_inputs,
            )
        )
    if router_output.primary_intent == "clarification_required" or router_output.clarification_questions:
        return MultiIntentExecutionPlan(
            summary="Waiting for required user input.",
            steps=[
                ExecutionStep(
                    index=0,
                    intent_name="clarification.required",
                    agent_intent=router_output.primary_intent,
                    status="needs_input",
                    missing_slots=router_output.clarification_questions or ["request.clarification"],
                    result_summary="Waiting for user clarification.",
                )
            ],
        )
    input_key = router_output.primary_intent
    structured = router_output.structured_intents[0] if router_output.structured_intents else None
    slots = {
        **(structured.slots if structured else {}),
        **request.agent_inputs.get(input_key, {}),
    }
    return MultiIntentExecutionPlan(
        summary=f"Prepared asynchronous {router_output.primary_intent} execution.",
        steps=[
            ExecutionStep(
                index=0,
                intent_name=structured.name if structured else f"{router_output.primary_intent}.execute",
                agent_intent=structured.agent_intent if structured else router_output.primary_intent,
                status="planned",
                slots=slots,
            )
        ],
    )
