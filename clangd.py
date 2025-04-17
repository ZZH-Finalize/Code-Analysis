from collections import deque
from typing import Union

import json
import os, sys
import asyncio
import logging
import time
import clangd_utils

script_path = os.path.abspath(os.path.dirname(sys.argv[0]))

class ClangdClient:
    def __init__(self, workspace_path: str = ''):
        self.workspace_path = workspace_path
        self.id = 10
        self.process: clangd_utils.subprocess.Popen = None
        self.opened_files = set()
        self.script_path = script_path
        self.endl = clangd_utils.get_endl()

        # requests or notifications that wait to be send
        self.send_queue = asyncio.Queue()
        # requests that wait for ack
        self.pending_queue = deque()

        # received response queue
        self.received_queue = asyncio.Queue()
        # clangd started flag
        self.clangd_started = asyncio.Event()

        if not os.path.exists(os.path.join(self.script_path, 'logs')):
            os.mkdir(os.path.join(self.script_path, 'logs'))

        time_tag = time.strftime('%Y-%m-%d-%H-%M-%S', time.localtime())

        self.logger = logging.getLogger(__name__)

        # default disable log
        self.logger.setLevel(logging.CRITICAL)
        for hdlr in self.logger.handlers:
            self.logger.removeHandler(hdlr)

        if len(sys.argv) > 1 and sys.argv[1].startswith('--enable-log'):
            args = sys.argv[1].split('=')
            if len(args) == 2:
                self.logger.setLevel(logging._nameToLevel.get(args[1], logging.INFO))
            else:
                self.logger.setLevel(logging.INFO)
            self.logger.addHandler(logging.FileHandler(os.path.join(self.script_path, 'logs', f'log-{time_tag}.txt'), mode='w'))

    def __done_cb(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError as e:
            self.logger.info(f'task: {task.get_name()} canceled')
        except Exception as e:
            self.logger.critical(f'task encounter an error: {e.with_traceback()}')
            asyncio.get_event_loop().stop()
            raise e

    async def __receive_task(self):
        while True:
            # clangd should be started before read any messages
            await self.clangd_started.wait()

            # wait for a line is read in buffer
            line: bytes = await asyncio.to_thread(self.process.stdout.readline)
            line: str = line.decode().removeprefix(self.endl)

            # is a response instead of a log information
            if line.startswith('Content-Length:'):
                # convert length
                length = int(line.split(':')[1].strip())
                # skip empty line
                self.process.stdout.readline()
                # read remain data
                data = self.process.stdout.read(length).decode().removesuffix(self.endl)
                # convert to python dict
                response: dict = json.loads(data)
                # response with id
                if 'id' in response:
                    self.logger.debug(f'resp: {response}')

                    # there is no pending requests
                    if 0 == len(self.pending_queue):
                        # workdone progress should receive
                        if 'window/workDoneProgress/create' == response['method'] and \
                            'backgroundIndexProgress' == response['params']['token']:
                            self.logger.info('received workDoneProgress/create request')
                            await self.received_queue.put(response)
                            continue

                        # skip this response
                        self.logger.info(f'drop response for: {response['method']}')
                        continue

                    # peek the first request in the pending_requests list
                    request = self.pending_queue[0]

                    # id unmatched
                    if request['id'] != request['id']:
                        self.logger.info(f'unknown resp for id: {request['id']}')
                        continue

                    if 'method' in response:
                        if request['method'] != response['method']:
                            self.logger.info(f'unknown resp for: {response['method']}({request['id']})')
                            continue

                    self.logger.info(f'receive resp for {request['method']}({request['id']})')
                    # put response to the received queue
                    await self.received_queue.put(response)
                    # remove the corresponding request
                    self.pending_queue.popleft()
                # no id in response
                else:
                    # progress report, should be received
                    if '$/progress' == response['method']:
                        await self.received_queue.put(response)
                        continue

                    self.logger.info(f'received no id msg: {response}')
            # not started with Content-Length, might be a log information
            else:
                line = line.removesuffix(self.endl)
                if line:
                    self.logger.debug(f'received log: {line}')

    async def __send_task(self):
        while True:
            # clangd should be started before send any messages
            await self.clangd_started.wait()
            # wait for send queue data available
            request, need_resp = await self.send_queue.get()
            # convert dict to json string
            message = json.dumps(request)
            # add message header
            req = f'Content-Length: {len(message)}\r\n\r\n{message}'.encode()

            if 'method' in request:
                log_info = f'write a message: {request['method']}'
            else:
                log_info = f'write a message: {request} ...'
            # need response means this is a request instead of a notification
            if need_resp:
                log_info += f'({request.get('id', None)})'
                # put request into pending queue waiting for response
                self.pending_queue.append(request)
            self.logger.info(log_info)

            # write formated message and flush write buffer
            await asyncio.to_thread(self.process.stdin.write, req)
            await asyncio.to_thread(self.process.stdin.flush)

    async def _send(self, need_resp: bool, **kwargs):
        if not self.clangd_started.is_set():
            raise RuntimeError('analyzer is down, please call start_analyzer first')

        # make request body
        request = {'jsonrpc': '2.0', **kwargs}

        # put request to sending queue
        await self.send_queue.put((request, need_resp))

    def get_id(self):
        self.id = self.id + 1

        if self.id < 0:
            raise RuntimeError('id exhausted !')

        return self.id

    async def start(self, workspace_path: str = ''):
        if '' == workspace_path:
            raise RuntimeError('workspace_path cannot be an empty path')

        # if process started
        if None != self.process:
            # and workspace changed
            if workspace_path != self.workspace_path:
                self.logger.info('restart server')
                # restart server
                await self.stop()
            # workspace does not change
            else:
                return

        # process cwd
        self.workspace_path = workspace_path
        self.logger.info(f'os cwd switch to {workspace_path}')
        os.chdir(self.workspace_path)

        # launch clangd process
        self.process, cdb_file, clangd_path = clangd_utils.create_clangd_process(self.workspace_path, '--log=verbose', '--background-index')
        self.logger.info(f'find clangd: {clangd_path}')

        # set clangd start flag
        self.clangd_started.set()

        # start running receive task
        self.receive_task = asyncio.create_task(self.__receive_task(), name='receive_task')
        self.send_task = asyncio.create_task(self.__send_task(), name='send_task')

        self.receive_task.add_done_callback(self.__done_cb)
        self.send_task.add_done_callback(self.__done_cb)

        # load init param
        with open(os.path.join(self.script_path, 'init_param.json'), encoding='utf-8') as f:
            param = json.loads(await asyncio.to_thread(f.read))

        # perform initialize sequence
        await self.send_request('initialize', param)
        await self.send_notification('initialized', {})

        # find a random file from cdb
        with open(cdb_file, encoding='utf-8') as f:
            cdb = json.loads(await asyncio.to_thread(f.read))

        # send did open request to force clangd load cdb
        await self.did_open(os.path.join(cdb[0]['directory'], cdb[0]['file']))
        # wait for clangd index the project
        await self.wait_for_background_index_down()

    async def stop(self):
        self.logger.info('stop server')

        self.receive_task.cancel()
        self.send_task.cancel()

        self.process.terminate()
        self.process = None
        self.workspace_path = ''
        self.opened_files.clear()

        # clear queues
        self.send_queue = asyncio.Queue()
        self.pending_queue.clear()
        self.received_queue = asyncio.Queue()

        # clear flags
        self.clangd_started.clear()

    async def send_request(self, method: str, params: dict):
        # send request with id
        await self._send(True, method=method, params=params, id=self.get_id())

        # wait for response
        return await self.received_queue.get()

    async def send_notification(self, method: str, params: dict):
        # send notification without id
        await self._send(False, method=method, params=params)

    async def wait_for_background_index_down(self):
        request = await self.received_queue.get()

        if request['method'] != 'window/workDoneProgress/create':
            self.logger.info(f'unexpected request : {request['method']}')
            raise RuntimeError('received error request')

        # send response to clangd
        await self._send(False, id=request['id'], result=None)

        # loop handle $/progress notification until it is done
        done_flag = False
        percentage = 0

        while False == done_flag:
            progress = await self.received_queue.get()
            # self.logger.info(f'progress: {json.dumps(progress, indent=4)}')
            kind = progress['params']['value']['kind']

            if 'end' == kind:
                done_flag = True
                percentage = 100
            elif 'report' == kind:
                percentage = int(progress['params']['value']['percentage'])
            
            self.logger.info(f'clangd indexing progress: {percentage}%')
            

    async def did_open(self, fn: str):
        file = os.path.abspath(fn)

        # if this file already opened
        if fn in self.opened_files:
            # skip it
            return file

        with open(file, encoding='utf-8') as f:
            await self.send_notification('textDocument/didOpen', {
                'textDocument': {
                    'uri': clangd_utils.fn_to_uri(file),
                    'languageId': 'c',
                    'version': 1,
                    'text': await asyncio.to_thread(f.read)
                }
            })

        # record opened file
        self.opened_files.add(fn)

        return file

    async def did_close(self, fn: str):
        file = os.path.abspath(fn)

        await self.send_notification('textDocument/didClose', {
            'textDocument': {
                'uri': clangd_utils.fn_to_uri(file)
            }
        })

        self.opened_files.remove(fn)

    async def workspace_symbol(self, symbol: str):
        return await self.send_request('workspace/symbol', {
            'query': symbol
        })

    async def document_symbol(self, uri: str):
        return await self.send_request('textDocument/documentSymbol', {
            'textDocument': {
                'uri': uri
            }
        })

    async def document_references(self, uri: str, line: int, character: int):
        reference = await self.send_request('textDocument/references', {
            'textDocument': {'uri': uri},
            'context': {'includeDeclaration': True},
            'position': {
                'line': int(line),
                'character': int(character)
            },
        })

        clangd_utils.check_result(reference)
        return reference

    async def document_definition(self, uri: str, line: int, character: int):
        definition = await self.send_request('textDocument/definition', {
            'textDocument': {'uri': uri},
            'position': {
                'line': int(line),
                'character': int(character)
            },
        })

        clangd_utils.check_result(definition)
        return definition

    async def find_symbol_definition(self, symbol: str):
        # find symbol location first
        symbol_loc = await self.locate_symbol(symbol)
        # open the file where the symbol is located
        await self.did_open(clangd_utils.uri_to_fn(symbol_loc['uri']))

        # find symbol definition
        definition = await self.document_definition(symbol_loc['uri'], **symbol_loc['range']['start'])

        # this means the symbol_loc is the actual definition
        if definition['result'][0]['uri'].endswith('.h'):
            definition = {'result': [symbol_loc]}

        return clangd_utils.extract_list(definition, self.workspace_path)

    async def find_symbol_references(self, symbol: str) -> Union[list, str]:
        # find symbol location first
        symbol_loc = await self.locate_symbol(symbol)
        # open the file where the symbol is located
        await self.did_open(clangd_utils.uri_to_fn(symbol_loc['uri']))

        # find symbol references
        reference = await self.document_references(symbol_loc['uri'], **symbol_loc['range']['start'])

        return clangd_utils.extract_list(reference, self.workspace_path)

    async def locate_symbol(self, symbol: str) -> Union[list, str, bool, dict]:
        symbol_resp = await self.workspace_symbol(symbol)

        clangd_utils.check_result(symbol_resp)
        return symbol_resp['result'][0]['location']


async def main():
    client = ClangdClient()
    workspace = os.path.join(script_path, 'target_proj')

    await client.start(workspace)

    print('clangd started')

    print(await client.find_symbol_definition('test_fun'))

    await client.stop()

    await client.start(workspace)
    print('clangd restarted')
    print(await client.find_symbol_definition('test_fun'))
    await client.stop()

    print('program done')

if __name__ == '__main__':
        asyncio.run(main())
