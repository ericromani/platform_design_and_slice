"""Unit tests for your business logic (app/work.py). Fill these in as you build."""

import pytest

from app.work import Rejected, process


def test_processes_valid_item():
    assert process({"id": "42"})["status"] == "processed"


def test_rejects_invalid_item():
    with pytest.raises(Rejected):
        process({})


# TODO: add a test per rule you add to process(). For AWS calls, use moto:
#   from moto import mock_aws
#   @mock_aws
#   def test_writes_to_table(): ...
