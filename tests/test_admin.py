import pytest
from fastapi import HTTPException

import config
import removal


def test_alcance_de_borrado():
    assert removal._chunk_scope("ana", False) == {"metadata.owner": "ana"}
    admin = removal._chunk_scope("admin", True)
    assert {"metadata.owner": "admin"} in admin["$or"] and {"metadata.visibility": "public"} in admin["$or"]
    assert not any("private" in str(c) for c in admin["$or"])   # nunca los privados de otros


def test_actor_exige_contrasena_para_admin(monkeypatch):
    import main
    monkeypatch.setattr(config, "ADMIN_TOKEN", "secreto")
    assert main._actor("ana", None) is False                  # un usuario normal no necesita token
    assert main._actor("ana", "secreto") is False             # y la cabecera no le da poderes
    assert main._actor("admin", "secreto") is True
    for bad in (None, "", "otro"):
        with pytest.raises(HTTPException) as e:
            main._actor("admin", bad)
        assert e.value.status_code == 403


def test_admin_desactivado_sin_token_configurado(monkeypatch):
    import main
    monkeypatch.setattr(config, "ADMIN_TOKEN", None)
    with pytest.raises(HTTPException) as e:
        main._actor("admin", "lo-que-sea")
    assert e.value.status_code == 403
    assert main._actor("ana", None) is False
