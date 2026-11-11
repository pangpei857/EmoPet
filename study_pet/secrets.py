"""Windows user-bound encrypted API credentials. Never stored in settings JSON."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from .chat_core import endpoint_origin


class _Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data,decrypt=False):
    if os.name!='nt':raise OSError('当前版本使用Windows本机加密保存密钥。')
    crypt32=ctypes.WinDLL('crypt32',use_last_error=True);kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    buffer=ctypes.create_string_buffer(data)
    source=_Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=_Blob()
    if decrypt:
        function=crypt32.CryptUnprotectData
        function.argtypes=[ctypes.POINTER(_Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_Blob)]
        args=(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    else:
        function=crypt32.CryptProtectData
        function.argtypes=[ctypes.POINTER(_Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_Blob)]
        args=(ctypes.byref(source),'MomoStudyPet DeepSeek credential',None,None,None,1,ctypes.byref(target))
    function.restype=wintypes.BOOL
    kernel32.LocalFree.argtypes=[ctypes.c_void_p];kernel32.LocalFree.restype=ctypes.c_void_p
    if not function(*args):raise OSError('Windows本机密钥加密或解密失败，请重新填写密钥。')
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel32.LocalFree(target.data)


class KeyVault:
    def __init__(self,directory):self.path=Path(directory)/'deepseek.key';self.error=''

    def save(self,key,base_url):
        key=key.strip()
        if not key or len(key)>1000 or any(c in key for c in '\r\n'):raise ValueError('请填写有效的API Key。')
        data=json.dumps({'origin':endpoint_origin(base_url),'key':key},ensure_ascii=False).encode('utf-8')
        encrypted=_crypt(data);self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp');temporary.write_bytes(encrypted);os.replace(temporary,self.path)
        self.error=''

    def load(self,base_url):
        if not self.path.exists():return ''
        try:
            data=json.loads(_crypt(self.path.read_bytes(),True).decode('utf-8'))
            self.error=''
            return str(data['key']) if data.get('origin')==endpoint_origin(base_url) else ''
        except (OSError,ValueError,KeyError,TypeError):
            self.error='已保存的密钥无法读取，请在这台电脑上重新填写。';return ''

    def remove(self):
        self.path.unlink(missing_ok=True);self.error=''
