"""
Base Exception Classes for Flask-AppBuilder

This module contains the foundational exception classes that other modules can import
without circular dependencies.
"""

from typing import Optional


class FABException(Exception):
    """Base FAB Exception"""

    def __init__(self, *args, exception: Optional[Exception] = None) -> None:
        self.exception = exception
        super().__init__(*args)

    def __str__(self):
        return (
            f"{self.__class__.__name__}: {self.exception.__class__.__name__}"
            if self.exception
            else super().__str__()
        )