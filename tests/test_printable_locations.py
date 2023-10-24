# pylint: disable=redefined-outer-name
import pytest

from rtruffle.source_section import SourceCoordinate, SourceSection
from som.compiler.ast.variable import Local
from som.interpreter.ast.nodes.specialized.down_to_do_node import (
    get_printable_location as pl_dtd,
)
from som.interpreter.ast.nodes.specialized.literal_to_do import (
    get_printable_location as pl_ltd,
    ToDoInlined,
)
from som.interpreter.ast.nodes.specialized.literal_while import (
    get_printable_location_while as pl_while,
    WhileInlinedNode,
)
from som.interpreter.ast.nodes.specialized.to_by_do_node import (
    get_printable_location as pl_tbd,
)
from som.interpreter.ast.nodes.specialized.to_do_node import (
    get_printable_location as pl_td,
)
from som.vm.symbols import symbol_for
from som.vmobjects.clazz import Class
from som.vmobjects.method_ast import AstMethod, get_printable_location as pl_method


@pytest.fixture
def method(source_section):
    sig = symbol_for("test")
    clazz = Class()
    clazz.set_name(symbol_for("Test"))
    method = AstMethod(sig, None, [], 0, 0, [], None, None)
    method.set_holder(clazz)
    method.source_section = source_section
    return method


@pytest.fixture
def source_section():
    coord = SourceCoordinate(1, 1, 1)
    return SourceSection(None, "Test>>test", coord, 0, "test.som")


def test_pl_dtd(method):
    assert pl_dtd(method) == "#to:do: Test>>test"


def test_pl_ltd(source_section):
    node = ToDoInlined(None, None, None, Local("", 1, source_section), source_section)

    assert pl_ltd(node) == "#to:do: test.som:1:1"


def test_while(source_section):
    node = WhileInlinedNode(None, None, None, source_section)
    assert pl_while(node) == "while test.som:1:1"


def test_tbd(method):
    assert pl_tbd(method) == "#to:do: Test>>test"


def test_td(method):
    assert pl_td(method) == "#to:do: Test>>test"


def test_method(method):
    assert pl_method(method) == "Test>>test"
