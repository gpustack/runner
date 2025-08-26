from __future__ import annotations

import json
from importlib import resources

__all__ = ["load"]


def load(filename: str, callback: callable | None = None) -> list[tuple]:
    """
    Load a fixture file and return its content as a list.

    :param filename: The name of the fixture file to load.
    :param callback: A callback function to process the loaded data.
    :return: The content of the fixture file as a list.
    """
    data_path = resources.files(__package__).joinpath(filename)
    with data_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if callback:
        return callback(data)
    return data
