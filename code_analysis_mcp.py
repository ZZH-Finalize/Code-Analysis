# from pylsp import LspClient
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, GetPromptResult, PromptMessage, Prompt
from typing import Any
from collections.abc import Sequence
import json

from tools import tool_list

server = Server('code-analysis-mcp',
instructions='''This MCP server provides a set of tools for code analysis, enabling fast and precise symbol lookup. When using these tools, you should first call start_analyzer to initialize the analyzer, passing the root directory of the code as a parameter. Once the analyzer is started, other interfaces can be invoked.

The find_definition tool provides functionality to locate the position where a variable or function is defined. It is typically used during code analysis when you need to inspect the implementation of a called function. This tool requires a variable name or function name as a parameter.

The find_references tool enables locating the positions where a variable or function is referenced or used. It is commonly used to determine where a specific function is called during code analysis. Like find_definition, this tool also requires a variable name or function name as a parameter.''',
)

tool_table = {}

@server.list_tools()
async def list_tools() -> list[Tool]:
    tool_register_list: list[Tool] = []

    for tool in tool_list:
        tool_register_list.append(Tool(
            name=tool.__name__,
            description=tool.__doc__,
            inputSchema=tool.model_json_schema()
        ))

    return tool_register_list

@server.call_tool()
async def call_tool(name: str, arg: Any) -> Sequence[TextContent]:
    if name not in tool_table:
        raise ValueError(f'unknown tool: {name}')

    result = await tool_table[name].exec(arg)

    if None == result:
        result = True

    return [
        TextContent(
            text=json.dumps(result),
            type='text'
        )
    ]

# @server.get_prompt()
# async def get_prompt(name: str, arg: dict[str, str] | None) -> GetPromptResult:
#     return GetPromptResult(description='desc', messages=[
#         PromptMessage(
#             role="user",
#             content=TextContent(
#                 text=f'input name: {name}, input arg: {arg}',
#                 type='text'
#             )
#         )
#     ])

# @server.list_prompts()
# async def list_prompts() -> list[Prompt]:
#     return [
#         Prompt(
#             name='analysis',
#             description='first desc',
#         )
#     ]

async def main():
    global tool_table

    for tool in tool_list:
        tool_table.update({tool.__name__: tool})

    async with stdio_server() as (read_stream, write_stream):
        options = server.create_initialization_options()
        # options.capabilities.performance = 'very fast'
        await server.run(read_stream, write_stream, options)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
