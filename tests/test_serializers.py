"""Wire-value serializer tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from supabase_orm import register_serializer
from supabase_orm._serializers import serialize


def test_json_native_passthrough():
    assert serialize("x") == "x"
    assert serialize(1) == 1
    assert serialize(1.5) == 1.5
    assert serialize(True) is True
    assert serialize(None) is None


def test_uuid_serialized_to_str():
    u = UUID("12345678-1234-5678-1234-567812345678")
    out = serialize(u)
    assert isinstance(out, str) and out == str(u)


def test_datetime_isoformat():
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert serialize(dt) == dt.isoformat()


def test_date_isoformat():
    d = date(2024, 1, 2)
    assert serialize(d) == "2024-01-02"


def test_decimal_to_str():
    assert serialize(Decimal("1.50")) == "1.50"


def test_enum_value():
    class Color(str, Enum):
        RED = "red"

    assert serialize(Color.RED) == "red"


def test_pydantic_basemodel_dumped_to_json_dict():
    class M(BaseModel):
        x: int
        y: UUID

    m = M(x=1, y=UUID("12345678-1234-5678-1234-567812345678"))
    out = serialize(m)
    assert out == {"x": 1, "y": "12345678-1234-5678-1234-567812345678"}


def test_dict_recursion():
    out = serialize({"id": UUID(int=0), "n": 1})
    assert out == {"id": str(UUID(int=0)), "n": 1}


def test_list_and_tuple_and_set_recursion():
    assert serialize([UUID(int=0), 1]) == [str(UUID(int=0)), 1]
    assert serialize((UUID(int=0),)) == [str(UUID(int=0))]
    out = serialize({1, 2, 3})
    assert sorted(out) == [1, 2, 3]


def test_register_serializer_custom_type():
    class Money:
        def __init__(self, cents: int) -> None:
            self.cents = cents

    register_serializer(Money, lambda v: v.cents)
    assert serialize(Money(500)) == 500


def test_unknown_type_passes_through_unchanged():
    sentinel = object()
    assert serialize(sentinel) is sentinel
