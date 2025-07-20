# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

datas = []
datas += copy_metadata('aiohappyeyeballs')
datas += copy_metadata('aiohttp')
datas += copy_metadata('aiosignal')
datas += copy_metadata('altgraph')
datas += copy_metadata('annotated-types')
datas += copy_metadata('anthropic')
datas += copy_metadata('anyio')
datas += copy_metadata('asyncer')
datas += copy_metadata('attrs')
datas += copy_metadata('backoff')
datas += copy_metadata('beautifulsoup4')
datas += copy_metadata('boto3')
datas += copy_metadata('botocore')
datas += copy_metadata('browser-use')
# Add browser-use data files including templates
datas += collect_data_files('browser_use')
datas += copy_metadata('cachetools')
datas += copy_metadata('certifi')
datas += copy_metadata('charset-normalizer')
datas += copy_metadata('click')
datas += copy_metadata('Cython')
datas += copy_metadata('defusedxml')
datas += copy_metadata('diskcache')
datas += copy_metadata('distro')
datas += copy_metadata('dnspython')
datas += copy_metadata('docker')
datas += copy_metadata('eval_type_backport')
datas += copy_metadata('faiss-cpu')
datas += copy_metadata('fastapi')
datas += copy_metadata('filelock')
datas += copy_metadata('filetype')
datas += copy_metadata('frozenlist')
datas += copy_metadata('fsspec')
datas += copy_metadata('google-ai-generativelanguage')
datas += copy_metadata('google-api-core')
datas += copy_metadata('google-api-python-client')
datas += copy_metadata('google-auth')
datas += copy_metadata('google-auth-httplib2')
datas += copy_metadata('google-auth-oauthlib')
datas += copy_metadata('googleapis-common-protos')
datas += copy_metadata('greenlet')
datas += copy_metadata('grpcio')
datas += copy_metadata('grpcio-status')
datas += copy_metadata('h11')
datas += copy_metadata('h2')
datas += copy_metadata('hpack')
datas += copy_metadata('httpcore')
datas += copy_metadata('httplib2')
datas += copy_metadata('httpx')
datas += copy_metadata('huggingface-hub')
datas += copy_metadata('hyperframe')
datas += copy_metadata('idna')
datas += copy_metadata('Jinja2')
datas += copy_metadata('jiter')
datas += copy_metadata('jmespath')
datas += copy_metadata('joblib')
datas += copy_metadata('jsonpatch')
datas += copy_metadata('jsonpointer')
datas += copy_metadata('langchain')
datas += copy_metadata('langchain-anthropic')
datas += copy_metadata('langchain-aws')
datas += copy_metadata('langchain-core')
datas += copy_metadata('langchain-deepseek')
datas += copy_metadata('langchain-google-genai')
datas += copy_metadata('langchain-ollama')
datas += copy_metadata('langchain-openai')
datas += copy_metadata('langchain-text-splitters')
datas += copy_metadata('langsmith')
datas += copy_metadata('lxml')
datas += copy_metadata('macholib')
datas += copy_metadata('markdown-it-py')
datas += copy_metadata('markdownify')
datas += copy_metadata('MarkupSafe')
datas += copy_metadata('mdurl')
datas += copy_metadata('mem0ai')
datas += copy_metadata('monotonic')
datas += copy_metadata('motor')
datas += copy_metadata('mpmath')
datas += copy_metadata('multidict')
datas += copy_metadata('nest-asyncio')
datas += copy_metadata('networkx')
datas += copy_metadata('numpy')
datas += copy_metadata('oauth2client')
datas += copy_metadata('oauthlib')
datas += copy_metadata('ollama')
datas += copy_metadata('openai')
datas += copy_metadata('orjson')
datas += copy_metadata('packaging')
datas += copy_metadata('pandas')
datas += copy_metadata('pillow')
datas += copy_metadata('playwright')
datas += copy_metadata('portalocker')
datas += copy_metadata('posthog')
datas += copy_metadata('propcache')
datas += copy_metadata('proto-plus')
datas += copy_metadata('protobuf')
datas += copy_metadata('psutil')
datas += copy_metadata('psycopg2-binary')
datas += copy_metadata('pyasn1')
datas += copy_metadata('pyasn1_modules')
datas += copy_metadata('pyautogen')
datas += copy_metadata('pydantic')
datas += copy_metadata('pydantic_core')
datas += copy_metadata('pyee')
datas += copy_metadata('Pygments')
datas += copy_metadata('pyinstaller')
datas += copy_metadata('pyinstaller-hooks-contrib')
datas += copy_metadata('pymongo')
datas += copy_metadata('pyobjc-core')
datas += copy_metadata('pyobjc-framework-Cocoa')
datas += copy_metadata('pyparsing')
datas += copy_metadata('pyperclip')
datas += copy_metadata('python-dateutil')
datas += copy_metadata('python-dotenv')
datas += copy_metadata('pytz')
datas += copy_metadata('PyYAML')
datas += copy_metadata('qdrant-client')
datas += copy_metadata('regex')
datas += copy_metadata('requests')
datas += copy_metadata('requests-oauthlib')
datas += copy_metadata('requests-toolbelt')
datas += copy_metadata('rich')
datas += copy_metadata('rsa')
datas += copy_metadata('s3transfer')
datas += copy_metadata('safetensors')
datas += copy_metadata('scikit-learn')
datas += copy_metadata('scipy')
datas += copy_metadata('screeninfo')
datas += copy_metadata('sentence-transformers')
datas += copy_metadata('setuptools')
datas += copy_metadata('shellingham')
datas += copy_metadata('simplegmail')
datas += copy_metadata('six')
datas += copy_metadata('sniffio')
datas += copy_metadata('soupsieve')
datas += copy_metadata('SQLAlchemy')
datas += copy_metadata('starlette')
datas += copy_metadata('sympy')
datas += copy_metadata('tabulate')
datas += copy_metadata('tenacity')
datas += copy_metadata('termcolor')
datas += copy_metadata('threadpoolctl')
datas += copy_metadata('tiktoken')
datas += copy_metadata('together')
datas += copy_metadata('tokenizers')
datas += copy_metadata('torch')
datas += copy_metadata('tqdm')
datas += copy_metadata('transformers')
datas += copy_metadata('typer')
datas += copy_metadata('typing-inspection')
datas += copy_metadata('typing_extensions')
datas += copy_metadata('tzdata')
datas += copy_metadata('uritemplate')
datas += copy_metadata('urllib3')
datas += copy_metadata('uvicorn')
datas += copy_metadata('yarl')
datas += copy_metadata('zstandard')
# Add missing critical packages that may cause metadata errors
datas += copy_metadata('sniffio')


a = Analysis(
    ['run_server.py'],  # Changed from main.py to run_server.py
    pathex=['.', 'routers', 'utilities', 'configs', 'capabilities'],  # Add current directory first, then other module paths
    binaries=[],
    datas=[
        ('code', 'code'),  # Include the code directory
        ('configs', 'configs'),  # Include configs directory  
        ('logs', 'logs'),  # Include logs directory
        ('images', 'images'),  # Include images directory
        ('static', 'static'),  # Include static directory
        ('templates', 'templates'),  # Include templates directory
        ('routers/*.py', 'routers'),  # Include routers Python files
        ('utilities/*.py', 'utilities'),  # Include utilities Python files
        ('capabilities', 'capabilities'),  # Include capabilities as data
        ('dependencies.py', '.'),  # Include dependencies module
        ('initialization.py', '.'),  # Include initialization module
        ('.env', '.'),  # Include .env file at root level for absolute path loading
        ('build/base_venv', 'base_venv'),  # Include base virtual environment for code execution
        ('bundled_python/python-darwin-arm64', 'bundled_python/python-darwin-arm64'),  # Include bundled Python distribution
    ] + datas,
    hiddenimports=[
        # FastAPI and Uvicorn related imports
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.loops.uvloop',
        'uvicorn.config',
        'uvicorn.server',
        'fastapi.routing',
        'fastapi.openapi.utils',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'starlette.middleware.cors',
        'starlette.responses',
        'pydantic.json_schema',
        'pydantic.v1',
        'email_validator',
        # Multiprocessing modules (fix for PyInstaller)
        'multiprocessing',
        'multiprocessing.connection',
        'multiprocessing.context',
        'multiprocessing.pool',
        'multiprocessing.queues',
        'multiprocessing.spawn',
        '_multiprocessing',
        # Database and async related
        'motor.motor_asyncio',
        'pymongo',
        'asyncio',
        # Mem0 specific imports
        'mem0.configs.vector_stores',
        'mem0.configs.vector_stores.qdrant',
        # Additional imports for your dependencies
        'anthropic',
        'openai',
        'langchain',
        'langchain_anthropic',
        'langchain_openai',
        'langchain_core',
        'boto3',
        'botocore',
        'requests',
        'httpx',
        'aiohttp',
        'dotenv',
        'python_dotenv',
        # Logging and utilities
        'logging',
        'logging.handlers',
        'contextlib',
        # Browser automation
        'playwright',
        'selenium',
        # AI/ML related
        'torch',
        'numpy',
        'pandas',
        'transformers',
        'sentence_transformers',
        'faiss',
        'qdrant_client',
        # Application modules
        'routers',
        'routers.chat',
        'routers.ws',
        'utilities',
        'utilities.logging',
        'utilities.mongodb_service',
        'utilities.storage',
        'utilities.external_memory',
        'utilities.custom_manager',
        'utilities.venv_manager',
        'dependencies',
        'configs',
        'configs.settings',
        'configs.llm_configs_manager',
        'initialization',
        'capabilities',
        'capabilities.python_developer',
        'capabilities.python_developer.manager',
        'capabilities.python_developer.prompts',
        'capabilities.python_developer.response_format',
        'capabilities.email_manager',
        'capabilities.email_manager.manager',
        'capabilities.email_manager.prompts',
        # Autogen related
        'autogen',
        'autogen.agentchat',
        'autogen.agentchat.agent',
        'autogen.agentchat.assistant_agent',
        'autogen.agentchat.user_proxy_agent',
        'autogen.agentchat.groupchat',
        'autogen.agentchat.conversable_agent',
        'autogen.coding',
        'autogen.coding.local_commandline_code_executor',
        'autogen.code_utils',
        'autogen.io',
        # Missing packages
        'loguru',
        'nest_asyncio',
        'simplegmail',
        # Additional missing modules that might be needed
        'starlette.staticfiles',
        'fastapi.staticfiles',
        'fastapi.responses',
        'pathlib',
        'concurrent.futures',
        'asyncio.events',
        'asyncio.tasks',
        'typing_extensions',
        # Critical packages for fixing runtime errors
        'sniffio',
        # Environment and configuration loading
        'dotenv',
        'python_dotenv',
        # Additional FastAPI/Starlette components
        'starlette.routing',
        'starlette.applications',
        'starlette.middleware',
        'starlette.exceptions',
        'starlette.requests',
        'starlette.responses',
        'starlette.status',
        # Additional async components
        'asyncio.subprocess',
        'asyncio.streams',
        'asyncio.protocols',
        # JSON and data handling
        'json',
        'orjson'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='omni-backend-app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX compression to avoid shared library issues
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
