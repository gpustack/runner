from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import _SubParsersAction


class SubCommand(ABC):
    """
    Base class for sub-commands.
    """

    @staticmethod
    @abstractmethod
    def register(parser: _SubParsersAction):
        """
        Register the sub-command with the given parser.
        This method should add a new sub-parser to the provided parser
        and set the `func` attribute to the class constructor.

        Args:
            parser: The sub-parsers action to register the command with.

        """
        raise NotImplementedError

    @abstractmethod
    def run(self):
        """
        Run the sub-command.
        """
        raise NotImplementedError
