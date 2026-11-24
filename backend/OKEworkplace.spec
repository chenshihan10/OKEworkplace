# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path as _Path
from PyInstaller.utils.hooks import collect_data_files

# 版本号唯一来源：仓库根目录 VERSION 文件
APP_VERSION = (_Path(SPECPATH).parent / 'VERSION').read_text(encoding='utf-8').strip()

# 核心依赖数据文件收集
datas = []
for pkg in ['requests', 'fastapi', 'uvicorn', 'apscheduler', 'webview', 'certifi']:
    try:
        datas.extend(collect_data_files(pkg))
    except Exception:
        pass

# 自定义数据文件
datas += [
    ('..\\frontend', 'frontend'),
    ('..\\VERSION', '.'),
    ('.env.example', '.'),  # 只打包示例配置，真实 .env 不随产物分发
]

block_cipher = None

a = Analysis(
    ['entry_exe.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'requests',
        'uvicorn', 'uvicorn.lifespan', 'uvicorn.protocols',
        'fastapi', 'fastapi.routing',
        'pydantic', 'pydantic.fields',
        'apscheduler', 'apscheduler.schedulers.background',
        'webview', 'webview.platforms.edgechromium',
        'clr_loader',
        'anyio', 'anyio.from_thread',
        'starlette', 'starlette.routing',
        'tzlocal', 'tzdata',
        'httpx',
        'dotenv',
        'certifi',
        'pystray', 'PIL',
        # 自定义模块
        'app', 'app.main', 'app.models', 'app.shutdown',
        'app.core', 'app.core.config', 'app.core.scheduler',
        'app.routes', 'app.routes.coins', 'app.routes.monitor',
        'app.routes.analysis', 'app.routes.network', 'app.routes.orders',
        'app.routes.predictions',          # V3.0
        'app.routes.risk',                 # 2.5.0
        'app.routes.mtf',                  # 2.5.0
        'app.routes.orderflow',            # 2.5.0
        'app.services', 'app.services.market_service',
        'app.services.oke_client', 'app.services.signal_engine',
        'app.services.indicator_service', 'app.services.network_service',
        'app.services.storage_manager', 'app.services.alert_store',
        'app.services.direction_tracker',  # v2.2
        'app.services.decision_engine',    # v2.2
        'app.services.db_store',           # v2.2
        'app.services.event_bus',          # v2.2
        'app.services.order_manager',      # v2.3
        'app.services.market_regime',      # V3.0
        'app.services.prediction_logger',  # V3.0
        'app.services.future_validator',   # V3.0
        'app.services.maintenance_service', # V3.0
        'app.services.backup_service',     # V3.0
        'app.services.multi_timeframe_service',  # 2.5.0
        'app.services.order_flow_service',       # 2.5.0
        'app.services.risk_service',             # 2.5.0
        'app.services.prediction_context',       # 2.5.0
        'app.model', 'app.model.market_score', 'app.model.capital_behavior',
        'app.strategy', 'app.strategy.trading_rules',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy', 'sympy', 'sphinx', 'docutils',
        'IPython', 'jupyter', 'nbformat', 'nbconvert', 'notebook',
        'sqlalchemy', 'alembic', 'babel',
        'openpyxl', 'xlrd', 'xlwt',
        'PIL.ImageQt', 'PIL.ImageTk',  # 保留基础 PIL 用于 pystray 托盘图标
        'PyQt5', 'PySide2', 'PySide6',
        'tkinter', 'turtle',
        'zmq', 'pyzmq', 'tornado',
        'cv2', 'opencv', 'sklearn', 'skimage',
        'nltk', 'spacy', 'tensorflow', 'torch', 'keras',
        'beautifulsoup4', 'lxml',
        'gevent', 'greenlet',
        'paramiko', 'bcrypt',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OKEworkplace_v%s' % APP_VERSION,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台，静默启动
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='..\\程序图标.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OKEworkplace_v%s' % APP_VERSION,
)
