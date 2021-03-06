from builtins import _PathLike
from typing import List, Optional, Any, Type, Union, Text, IO

class Archive:
    member_names: List[str]
    def member_is_file(self, name: str) -> bool: ...
    # TODO overload?
    def open_member(self, name: str, mode: str) -> IO[Any]: ...
    def extract(self, path: Any=..., members: Any=...) -> None: ...
    def __enter__(self) -> Archive: ...
    def __exit__(self, *args: Any) -> None: ...

class ZipArchive(Archive):
    pass

def open(name: Union[Text, '_PathLike[Any]'], mode: str, engine: Optional[Type[Archive]]=...) -> Archive: ...
