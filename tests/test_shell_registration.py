import importlib.util
from pathlib import Path
import uuid
import winreg
import pytest

spec=importlib.util.spec_from_file_location('preview_register',Path(__file__).parents[1]/'windows/preview/register.py')
register=importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)

def test_registry_refuses_foreign_and_restores(tmp_path):
    base='Software\\DracoConvTest\\'+str(uuid.uuid4())
    values=[(base,'handler','ours')]
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,base) as key: winreg.SetValueEx(key,'handler',0,winreg.REG_SZ,'foreign')
    with pytest.raises(RuntimeError): register.install_values(values,tmp_path/'state.json')
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,base,0,winreg.KEY_SET_VALUE) as key: winreg.DeleteValue(key,'handler')
    register.install_values(values,tmp_path/'state.json')
    register.uninstall_values(tmp_path/'state.json')
    with pytest.raises(FileNotFoundError):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,base) as key: winreg.QueryValueEx(key,'handler')
    try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER,base)
    except FileNotFoundError: pass

def test_effective_progid_handler_is_not_overwritten(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path.endswith('UserChoice') and name=='ProgId': return ['Foreign.App',winreg.REG_SZ]
        if path.startswith('Foreign.App\\shellex\\'): return ['{foreign}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    with pytest.raises(RuntimeError,match='handler'): register.values()


def test_default_progid_handler_is_not_overwritten(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path=='.drc': return ['Foreign.Default',winreg.REG_SZ]
        if path.startswith('Foreign.Default\\shellex\\'): return ['{foreign}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    with pytest.raises(RuntimeError,match='handler'): register.values()
