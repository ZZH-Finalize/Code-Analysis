from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent, Tool

from typing import Optional

import asyncio
from contextlib import AsyncExitStack

import os, sys

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None

    async def connect_to_server(self, server_script_path: str):
        '''连接到 MCP 服务器

        参数：
            server_script_path: 服务器脚本路径 (.py 或 .js)
        '''
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError('服务器脚本必须是 .py 或 .js 文件')

        # command = 'python' if is_python else 'node'
        if os.name == 'nt':
            cmd = 'python'
        elif os.name == 'posix':
            cmd = 'python3.12'
        else:
            raise RuntimeError('env not sup')

        print(f'cmd: {cmd}')

        server_params = StdioServerParameters(
            command=cmd,
            args=[server_script_path, '--enable-log=DEBUG'],
            env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        print('initialize res:', await self.session.initialize())

        # 列出可用工具
        response = await self.session.list_tools()
        tools = response.tools
        print('\n已连接到服务器，可用工具：', [tool.name for tool in tools])

    async def call_tool(self, tool_name, tool_args):
        resp_list = await self.session.call_tool(tool_name, tool_args)
        # for resp in resp_list.content:
        #     print(f'resp: {resp.text}')
        return resp_list.content[0].text

    async def cleanup(self):
        '''清理资源'''
        await self.exit_stack.aclose()
    
script_path = os.path.dirname(sys.argv[0])
workspace = os.path.abspath(os.path.join(script_path, '..', 'target_proj'))
test_cases = [
        ('start_analyzer', {'workspace_path': workspace}),
        ('stop_analyzer', None),

        ('start_analyzer', {'workspace_path': workspace}),
        ('start_analyzer', {'workspace_path': workspace}),

        ('find_references', {'symbol_name': 'main'}),
        ('find_definition', {'symbol_name': 'main'}),

        ('find_references', {'symbol_name': 'test_top'}),
        ('find_definition', {'symbol_name': 'test_top'}),

        ('find_references', {'symbol_name': 'test_fun1'}),
        ('find_definition', {'symbol_name': 'test_fun1'}),

        ('find_references', {'symbol_name': 'test_fun2'}),
        ('find_definition', {'symbol_name': 'test_fun2'}),

        ('find_references', {'symbol_name': 'main_local'}),
        ('find_definition', {'symbol_name': 'main_local'}),

        ('find_references', {'symbol_name': 'main_global'}),
        ('find_definition', {'symbol_name': 'main_global'}),

        ('find_references', {'symbol_name': 'test2_global'}),
        ('find_definition', {'symbol_name': 'test2_global'}),

        ('find_references', {'symbol_name': 'macro1'}),
        ('find_definition', {'symbol_name': 'macro1'}),

        ('find_references', {'symbol_name': 'macro2'}),
        ('find_definition', {'symbol_name': 'macro2'}),

        ('find_references', {'symbol_name': 'macro3'}),
        ('find_definition', {'symbol_name': 'macro3'}),

        ('stop_analyzer', None),
    ]

async def main():
    client = MCPClient()

    try:
        await client.connect_to_server(os.path.join(script_path, '..', 'code_analysis_mcp.py'))

        for tool, param in test_cases:
            res = await client.call_tool(tool, param)

            if None != param:
                key = list(param.keys())[0]
                value = list(param.values())[0]
                print(f'{tool}({key}: {value}) -> {res}')
            else:
                print(f'{tool}() -> {res}')

        # prompts = await client.session.list_prompts()

        # print(prompts.prompts[0].name)

        # response = await client.session.get_prompt(prompts.prompts[0].name, {
        #     'a': '1',
        #     'b': '2',
        #     'c': '3',
        # })

        # print(f'response.messages: {response.messages}')

    finally:
        await client.cleanup()

if '__main__' == __name__:
    asyncio.run(main())
