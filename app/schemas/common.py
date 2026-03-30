"""
Common schemas used across multiple endpoints.
"""

from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Consistent pagination wrapper for list endpoints.
    """
    items: List[T]
    page: int
    page_size: int
    total_count: int
    total_pages: int
