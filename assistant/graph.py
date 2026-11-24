import json
import logging
from collections.abc import Callable
from functools import partial
from time import perf_counter

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from assistant import tools as fleet_tools

SYSTEM_PROMPT: str = (
    "- Use only field names and values returned by tools. "
    "Do not invent labels or calculate dates or cycles. Say when data is missing.\n"
    "- If no unit is given, call fleet_status first.\n"
    "- For parts with no unit, call parts_for for the top units from fleet_status "
    "(up to three). Recommend only parts with needs_order=true.\n"
    "- Only say a request was drafted if draft_part_request returned its ID in this run."
)
MAX_TOOL_CALLS = 6
logger = logging.getLogger(__name__)


class AssistantState(MessagesState):
    tool_calls: list[dict]
    drafts: list[str]


def make_tools(ctx: fleet_tools.FleetContext) -> list[BaseTool]:
    tools = []
    for function in (
        fleet_tools.fleet_status,
        fleet_tools.engine_detail,
        fleet_tools.parts_for,
        fleet_tools.work_orders,
        fleet_tools.draft_work_order,
        fleet_tools.draft_part_request,
    ):
        # Fix the first argument to our fleet context and keep the tool's type hints.
        bound = partial(function, ctx)
        bound.__name__ = function.__name__
        bound.__qualname__ = function.__qualname__
        bound.__doc__ = function.__doc__
        bound.__annotations__ = function.__annotations__
        tools.append(StructuredTool.from_function(bound))
    return tools


def build_graph(
    model,
    tools: list[BaseTool],
    ctx: fleet_tools.FleetContext | None = None,
    on_step: Callable[[dict], None] = lambda s: None,
) -> CompiledStateGraph:
    tools_by_name = {tool.name: tool for tool in tools}

    def report_step(kind, name, args, result, started, outcome="ok"):
        duration_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "event=assistant_step kind=%s name=%s duration_ms=%d outcome=%s",
            kind,
            name,
            duration_ms,
            outcome,
        )
        on_step(
            {
                "kind": kind,
                "name": name,
                "args": args,
                "result": result[:200],
                "duration_ms": duration_ms,
            }
        )

    def call_model(state: AssistantState) -> dict:
        drafts = list(ctx.drafts_made) if ctx is not None else []
        # At the cap, write the stop message without calling the model again.
        if len(state.get("tool_calls", [])) >= MAX_TOOL_CALLS:
            reply = AIMessage(
                content=f"Stopped: tool-call limit ({MAX_TOOL_CALLS}) reached."
            )
            return {"messages": [reply], "drafts": drafts}

        started = perf_counter()
        try:
            reply = model.invoke(
                [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
            )
        except Exception as error:
            report_step("model", "model", {}, str(error), started, "error")
            raise
        report_step("model", "model", {}, reply.text, started)
        return {"messages": [reply], "drafts": drafts}

    def route_after_model(state: AssistantState) -> str:
        # A tool request goes to the tools node. An answer ends the graph.
        return "tools" if state["messages"][-1].tool_calls else END

    def call_tools(state: AssistantState) -> dict:
        calls = list(state.get("tool_calls", []))
        replies = []
        # One model reply may request several tools, so run only what fits.
        remaining = MAX_TOOL_CALLS - len(calls)
        for call in state["messages"][-1].tool_calls[:remaining]:
            name, args = call["name"], call["args"]
            started = perf_counter()
            outcome = "ok"
            try:
                if name not in tools_by_name:
                    raise ValueError(f"Unknown tool {name}.")
                result = tools_by_name[name].invoke(args)
                content = json.dumps(result)
                if isinstance(result, dict) and "error" in result:
                    outcome = "error"
            # Every tool failure becomes a message the model can answer from.
            except Exception as error:  # noqa: BLE001
                content = f"Error: {error}"
                outcome = "error"
            report_step("tool", name, args, content, started, outcome)
            calls.append({"name": name, "args": args})
            replies.append(
                ToolMessage(
                    content=content,
                    name=name,
                    tool_call_id=call["id"],
                    status="error" if outcome == "error" else "success",
                )
            )
        return {"messages": replies, "tool_calls": calls}

    graph = StateGraph(AssistantState)
    graph.add_node("model", call_model)
    graph.add_node("tools", call_tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "model")
    return graph.compile()


def run_question(graph: CompiledStateGraph, question: str) -> dict:
    state = graph.invoke({"messages": [HumanMessage(content=question)]})
    return {
        "answer": state["messages"][-1].text,
        "tool_calls": state.get("tool_calls", []),
        "drafts": state["drafts"],
    }


def mermaid(graph: CompiledStateGraph) -> str:
    return graph.get_graph().draw_mermaid()
