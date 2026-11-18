# ============================================================
#  app/__init__.py
#  ------------------------------------------------------------------
#  Bootstrap para que los modulos usen imports absolutos
#  (import config, import chat, ...) sin importar desde donde se lance
#  uvicorn. Al ejecutar `uvicorn app.main:app` desde la raiz del
#  proyecto, se anade el directorio app/ al sys.path para que estos
#  imports se resuelvan correctamente.
# ============================================================

import os
import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)