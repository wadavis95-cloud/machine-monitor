from asyncio import to_thread

from assistant.graph import build_graph, make_tools
from assistant.routes import chat_model_factory
from assistant.seed import DATA_DIR
from assistant.tools import load_context


async def graph():
    """Build the assistant graph for a Studio run."""
    db_path = DATA_DIR / "eam.sqlite"
    if not db_path.is_file():
        raise FileNotFoundError("Run make seed first.")

    # Each run gets its own draft list, just like a question in Flask.
    ctx = await to_thread(load_context, db_path, DATA_DIR)
    tools = make_tools(ctx)
    return build_graph(chat_model_factory().bind_tools(tools), tools, ctx=ctx)
