from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "请求成功"
    data: T


class ErrorDetail(BaseModel):
    code: str
    message: str

