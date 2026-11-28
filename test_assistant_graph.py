import logging
from itertools import count

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool


@pytest.fixture
def graph_api():
    # Import here so pytest can collect all seven tests before the graph is built.
    from assistant import graph

    return graph


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.messages = []

    def invoke(self, messages):
        self.messages = messages
        return self.replies.pop(0)


def _tool_call(name="fleet_status", args=None, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": {"top_n": 3} if args is None else args,
                "id": call_id,
            }
        ],
    )


class RepeatingToolModel:
    def __init__(self):
        self.call_numbers = count(1)

    def invoke(self, messages):
        return _tool_call(call_id=f"call-{next(self.call_numbers)}")


def test_system_prompt_keeps_draft_and_tool_rules(graph_api):
    prompt = graph_api.SYSTEM_PROMPT
    assert (
        "Only say a request was drafted if draft_part_request returned its ID in this run."
        in prompt
    )
    assert "Use only field names and values returned by tools" in prompt
    assert "Do not invent labels or calculate dates or cycles" in prompt
    assert "If no unit is given, call fleet_status first" in prompt
    assert "call parts_for for the top units" in prompt


# The graph runs the requested fleet tool and returns the model's final answer.
def test_graph_calls_tool_then_answers(graph_api, ctx):
    answer = "Engine X needs attention [fleet_status]."
    model = ScriptedModel(_tool_call(), AIMessage(content=answer))
    graph = graph_api.build_graph(model, graph_api.make_tools(ctx), ctx=ctx)

    result = graph_api.run_question(graph, "Which engines need attention?")

    assert result["answer"] == answer
    assert result["tool_calls"] == [{"name": "fleet_status", "args": {"top_n": 3}}]
    assert result["drafts"] == []
    assert any(isinstance(message, ToolMessage) for message in model.messages)


# The graph stops after six tool calls even when the model keeps asking for more.
def test_tool_call_cap_is_six(graph_api, ctx):
    steps = []
    graph = graph_api.build_graph(
        RepeatingToolModel(), graph_api.make_tools(ctx), ctx=ctx, on_step=steps.append
    )

    result = graph_api.run_question(graph, "Check the fleet.")

    assert [step["kind"] for step in steps].count("tool") == 6
    assert result["answer"] == "Stopped: tool-call limit (6) reached."


# The step callback sees the first model call, the tool call, and the final model call in order.
def test_on_step_sees_every_step_in_order(graph_api, ctx):
    steps = []
    model = ScriptedModel(_tool_call(), AIMessage(content="Fleet checked."))
    graph = graph_api.build_graph(
        model, graph_api.make_tools(ctx), ctx=ctx, on_step=steps.append
    )

    graph_api.run_question(graph, "Check the fleet.")

    assert [step["kind"] for step in steps] == ["model", "tool", "model"]


# Each model or tool step writes one log line with its name, elapsed time, and outcome.
def test_steps_are_logged(graph_api, ctx, caplog):
    model = ScriptedModel(_tool_call(), AIMessage(content="Fleet checked."))
    graph = graph_api.build_graph(model, graph_api.make_tools(ctx), ctx=ctx)

    with caplog.at_level(logging.INFO):
        graph_api.run_question(graph, "Check the fleet.")

    lines = [
        r.getMessage() for r in caplog.records if "event=assistant_step" in r.message
    ]
    assert len(lines) == 3
    for line, kind in zip(lines, ["model", "tool", "model"]):
        fields = dict(field.split("=", 1) for field in line.split())
        assert fields["kind"] == kind
        assert fields["name"]
        assert int(fields["duration_ms"]) >= 0
        assert fields["outcome"] == "ok"


# A tool exception reaches the model as an error message and the graph still answers.
def test_tool_error_does_not_crash_graph(graph_api, ctx):
    def broken_tool():
        """Simulate a tool failure."""
        raise RuntimeError("Fleet data unavailable")

    tools = graph_api.make_tools(ctx) + [StructuredTool.from_function(broken_tool)]
    answer = "I couldn't check the fleet."
    model = ScriptedModel(_tool_call("broken_tool", {}), AIMessage(content=answer))
    graph = graph_api.build_graph(model, tools, ctx=ctx)

    result = graph_api.run_question(graph, "Check the fleet.")

    assert result["answer"] == answer
    (message,) = [msg for msg in model.messages if isinstance(msg, ToolMessage)]
    assert "Fleet data unavailable" in message.content


# The Mermaid diagram includes both the model and tools nodes.
def test_mermaid_has_model_and_tools_nodes(graph_api, ctx):
    model = ScriptedModel(AIMessage(content="Fleet checked."))
    graph = graph_api.build_graph(model, graph_api.make_tools(ctx), ctx=ctx)

    diagram = graph_api.mermaid(graph)

    assert "model(model)" in diagram
    assert "tools(tools)" in diagram


# A quantity sent as text is saved as the integer 2.
def test_tool_args_are_coerced(graph_api, ctx):
    args = {"part_id": "P-HPC-01", "qty": "2", "reason": "Replace worn seal"}
    model = ScriptedModel(
        _tool_call("draft_part_request", args),
        AIMessage(content="Part request checked."),
    )
    graph = graph_api.build_graph(model, graph_api.make_tools(ctx), ctx=ctx)

    result = graph_api.run_question(graph, "Draft a request for two seal kits.")

    assert result["answer"] == "Part request checked."
    (draft,) = ctx.drafts.review_queue()
    qty = draft["payload"]["lines"][0]["qty"]
    assert type(qty) is int and qty == 2
    assert result["drafts"] == [draft["id"]]
