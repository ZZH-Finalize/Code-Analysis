from urllib.parse import urlparse, unquote
from urllib.request import pathname2url
from packaging import version
import fnmatch
import subprocess
import os

def get_endl() -> str:
    if os.name == 'nt':
        return '\r\n'
    elif os.name == 'posix':
        return '\n'

def uri_to_fn(uri: str):
    fn = unquote(urlparse(uri).path)
    if os.name == 'nt':
        fn = fn.removeprefix('/')
    return fn

def fn_to_uri(fn: str):
    return 'file:' + pathname2url(fn)

def check_result(response: dict) -> None:
    if 'error' in response:
        raise RuntimeError(f'error occurred: {response["message"]}')
    elif [] == response.get('result', []):
        raise RuntimeError('result not found')

def extract_list(response: dict, workspace_path: str) -> list[str]:
    res = []

    for ref in response['result']:
        rel_path = os.path.relpath(uri_to_fn(ref['uri']), workspace_path)
        line = ref['range']['start']['line']
        res.append(f'{rel_path}:{line}')

    return res

def search_cdb(path: str):
    for root, dir, files in os.walk(path):
        for file_path in fnmatch.filter(files, 'compile_commands.json'):
            return os.path.relpath(os.path.join(root, file_path), path)
    return None

def find_clangd(check_name: str = 'clangd'):
    clangd_abs_path = ''

    if os.name == 'nt':
        check_name = check_name + '.exe'

    for path in os.environ['PATH'].split(';'):
        clangd_abs_path = os.path.join(path, check_name)
        if os.path.exists(clangd_abs_path):
            return clangd_abs_path

    # check for vscode
    vscode_ext_dir = ''

    if os.name == 'nt':
        vscode_ext_dir = os.path.join(
            os.environ['USERPROFILE'],
            'AppData',
            'Roaming',
            'Code',
            'User',
            'globalStorage',
            'llvm-vs-code-extensions.vscode-clangd',
            'install'
        )
    elif os.name == 'posix':
        vscode_ext_dir = os.path.join(
            os.path.expanduser('~'),
            '.vscode-server',
            'data',
            'User',
            'globalStorage',
            'llvm-vs-code-extensions.vscode-clangd',
            'install'
        )
    else:
        raise RuntimeError('not supported')

    if not os.path.exists(vscode_ext_dir):
        return None

    latest = str(max(map(version.parse, os.listdir(vscode_ext_dir))))
    vscode_clangd = os.path.join(
        vscode_ext_dir,
        latest,
        'clangd_' + latest,
        'bin',
        check_name
    )

    if os.path.exists(vscode_clangd):
        return vscode_clangd

    return None

def create_clangd_process(cwd: str, *clangd_args, clangd_path: str = find_clangd()):
    __clangd_args = [
        clangd_path,
        '--function-arg-placeholders=1',
        '--header-insertion=iwyu',
        '--clang-tidy',
        '--all-scopes-completion',
        '--enable-config',
        '--cross-file-rename',
        # '--log=verbose',
        # '--background-index',
    ]

    cdb_file = search_cdb(cwd)
    cdb_path = os.path.dirname(cdb_file)

    if None == cdb_path:
        raise RuntimeError('no compile_commands.json found')
    
    __clangd_args.append(f'--compile-commands-dir={cdb_path}')
    __clangd_args.extend(clangd_args)

    process = subprocess.Popen(
        executable=clangd_path,
        args=__clangd_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
    )

    if None == process:
        raise RuntimeError('start clangd fail')

    return process, cdb_file, clangd_path
