# pylint: disable=redefined-outer-name,protected-access
import pytest

from rlib.string_stream import StringStream
from som.compiler.ast.method_generation_context import MethodGenerationContext
from som.compiler.ast.parser import Parser
from som.compiler.ast.variable import Argument
from som.compiler.class_generation_context import ClassGenerationContext
from som.interp_type import is_bytecode_interpreter
from som.interpreter.ast.frame import FRAME_AND_INNER_RCVR_IDX
from som.interpreter.ast.nodes.block_node import BlockNode, BlockNodeWithContext
from som.interpreter.ast.nodes.field_node import FieldReadNode, FieldIncrementNode
from som.interpreter.ast.nodes.global_read_node import _UninitializedGlobalReadNode
from som.interpreter.ast.nodes.literal_node import LiteralNode
from som.interpreter.ast.nodes.return_non_local_node import ReturnLocalNode
from som.interpreter.ast.nodes.sequence_node import SequenceNode
from som.interpreter.ast.nodes.specialized.int_inc_node import IntIncrementNode
from som.interpreter.ast.nodes.specialized.literal_and_or import (
    AndInlinedNode,
    OrInlinedNode,
)
from som.interpreter.ast.nodes.specialized.literal_if import (
    IfInlinedNode,
    IfElseInlinedNode,
)
from som.interpreter.ast.nodes.specialized.literal_to_do import ToDoInlined
from som.interpreter.ast.nodes.specialized.literal_while import WhileInlinedNode
from som.interpreter.ast.nodes.variable_node import (
    UninitializedReadNode,
    LocalFrameVarReadNode,
    UninitializedWriteNode,
)
from som.vm.current import current_universe
from som.vm.globals import trueObject, falseObject
from som.vm.symbols import symbol_for

pytestmark = pytest.mark.skipif(  # pylint: disable=invalid-name
    is_bytecode_interpreter(), reason="Tests are specific to AST interpreter"
)


def add_field(cgenc, name):
    cgenc.add_instance_field(symbol_for(name))


@pytest.fixture
def cgenc():
    gen_c = ClassGenerationContext(current_universe)
    gen_c.name = symbol_for("Test")
    return gen_c


@pytest.fixture
def mgenc(cgenc):
    mgenc = MethodGenerationContext(current_universe, cgenc, None)
    mgenc.add_argument("self", None, None)
    return mgenc


def parse_method(mgenc, source):
    parser = Parser(StringStream(source.strip()), "test", current_universe)
    return parser.method(mgenc)


@pytest.mark.parametrize(
    "arg_name,arg_idx",
    [
        ("arg1", 1),
        ("arg2", 2),
    ],
)
def test_access_arg_from_inlined_block(mgenc, arg_name, arg_idx):
    seq = parse_method(
        mgenc,
        """
        test: arg1 and: arg2 = ( true ifTrue: [ ARG ] )""".replace(
            "ARG", arg_name
        ),
    )

    assert isinstance(seq, SequenceNode)
    if_node = seq._exprs[0]

    assert isinstance(if_node, IfInlinedNode)
    assert if_node._expected_bool is trueObject

    if_body = if_node._body_expr
    assert isinstance(if_body, UninitializedReadNode)
    assert if_body._context_level == 0
    assert if_body.var._name == arg_name
    assert if_body.var.idx == arg_idx

    assert seq._exprs[1].is_self()


def test_access_self_from_inlined_block(mgenc):
    seq = parse_method(
        mgenc,
        """
        test: arg1 and: arg2 = ( true ifTrue: [ self ] )""",
    )

    assert isinstance(seq, SequenceNode)
    if_node = seq._exprs[0]

    assert isinstance(if_node, IfInlinedNode)
    assert if_node._expected_bool is trueObject

    if_body = if_node._body_expr
    assert isinstance(if_body, LocalFrameVarReadNode)
    assert if_body.is_self()

    assert seq._exprs[1].is_self()


def test_access_block_arg_from_inlined(mgenc):
    seq = parse_method(
        mgenc,
        """
        test = ( [:arg |
            arg.
            true ifTrue: [ arg ] ] )""",
    )

    assert isinstance(seq, SequenceNode)
    block_node = seq._exprs[0]

    assert isinstance(block_node, BlockNode)
    method = block_node._value
    seq = method.invokable.expr_or_sequence

    arg_read = seq._exprs[0]
    assert arg_read._context_level == 0
    assert arg_read.var._name == "arg"
    assert arg_read.var.idx == 1

    assert isinstance(seq._exprs[1], IfInlinedNode)

    body = seq._exprs[1]._body_expr
    assert isinstance(body, UninitializedReadNode)
    assert body._context_level == 0
    assert body.var._name == "arg"
    assert body.var.idx == 1

    assert body.var is arg_read.var


@pytest.mark.parametrize(
    "literal,lit_type",
    [
        ("0", LiteralNode),
        ("1", LiteralNode),
        ("-10", LiteralNode),
        ("3333", LiteralNode),
        ("'str'", LiteralNode),
        ("#sym", LiteralNode),
        ("1.1", LiteralNode),
        ("-2342.234", LiteralNode),
        ("true", LiteralNode),
        ("false", LiteralNode),
        ("nil", LiteralNode),
        ("SomeGlobal", _UninitializedGlobalReadNode),
        ("[]", BlockNode),
        ("[ self ]", BlockNodeWithContext),
    ],
)
def test_if_true_with_literal_return(mgenc, literal, lit_type):
    source = """
        test = (
            self method ifTrue: [ LITERAL ].
        )""".replace(
        "LITERAL", literal
    )
    ast = parse_method(mgenc, source)

    assert isinstance(ast._exprs[0], IfInlinedNode)

    body = ast._exprs[0]._body_expr
    assert isinstance(body, lit_type)


@pytest.mark.parametrize(
    "if_selector,expected_bool,unexpected_bool",
    [
        ("ifTrue:", trueObject, falseObject),
        ("ifFalse:", falseObject, trueObject),
    ],
)
def test_if_arg(mgenc, if_selector, expected_bool, unexpected_bool):
    ast = parse_method(
        mgenc,
        """
        test: arg = (
            #start.
            self method IF_SELECTOR [ arg ].
            #end
        )""".replace(
            "IF_SELECTOR", if_selector
        ),
    )

    assert isinstance(ast._exprs[1], IfInlinedNode)

    if_node = ast._exprs[1]
    assert if_node._expected_bool is expected_bool
    assert if_node._not_expected_bool is unexpected_bool


def test_if_true_and_inc_field(cgenc, mgenc):
    add_field(cgenc, "field")
    ast = parse_method(
        mgenc,
        """
        test: arg = (
            #start.
            (self key: 5) ifTrue: [ field := field + 1 ].
            #end
        )""",
    )

    assert isinstance(ast._exprs[1], IfInlinedNode)
    field_inc = ast._exprs[1]._body_expr

    assert isinstance(field_inc, FieldIncrementNode)

    assert field_inc.field_idx == 0
    assert isinstance(field_inc._self_exp, LocalFrameVarReadNode)
    assert field_inc._self_exp._frame_idx == FRAME_AND_INNER_RCVR_IDX


def test_if_true_and_inc_arg(mgenc):
    ast = parse_method(
        mgenc,
        """
        test: arg = (
            #start.
            (self key: 5) ifTrue: [ arg + 1 ].
            #end
        )""",
    )

    assert isinstance(ast._exprs[1], IfInlinedNode)
    inc_message = ast._exprs[1]._body_expr

    assert isinstance(inc_message, IntIncrementNode)

    arg_node = inc_message._rcvr_expr
    assert arg_node._context_level == 0
    assert arg_node.var._name == "arg"
    assert arg_node.var.idx == 1


def test_nested_ifs(cgenc, mgenc):
    add_field(cgenc, "field")
    ast = parse_method(
        mgenc,
        """
        test: arg = (
            true ifTrue: [
                false ifFalse: [
                  ^ field - arg
                ]
            ]
        )""",
    )

    assert isinstance(ast._exprs[0], IfInlinedNode)
    if_node = ast._exprs[0]
    assert isinstance(if_node._body_expr, IfInlinedNode)
    assert isinstance(if_node._body_expr._body_expr, ReturnLocalNode)

    msg = if_node._body_expr._body_expr._expr
    rcvr = msg._rcvr_expr
    assert isinstance(rcvr, FieldReadNode)
    assert isinstance(rcvr._self_exp, LocalFrameVarReadNode)
    assert rcvr._self_exp.is_self()

    arg = msg._arg_exprs[0]
    assert arg._context_level == 0
    assert isinstance(arg.var, Argument)
    assert arg.var._name == "arg"
    assert arg.var.idx == 1


def test_nested_ifs_and_locals(cgenc, mgenc):
    add_field(cgenc, "field")
    seq = parse_method(
        mgenc,
        """
        test: arg = (
          | a b c d |
          a := b.
          true ifTrue: [
            | e f g |
            e := 2.
            c := 3.
            false ifFalse: [
              | h i j |
              h := 1.
              ^ i - j - f - g - d ] ] )""",
    )

    if_true = seq._exprs[1]
    assert isinstance(if_true, IfInlinedNode)

    if_false = if_true._body_expr._exprs[2]
    assert isinstance(if_false, IfInlinedNode)

    body_if_false = if_false._body_expr._exprs

    write = body_if_false[0]
    assert isinstance(write, UninitializedWriteNode)
    assert write._context_level == 0
    assert write._var._name == "h"

    return_local = body_if_false[1]
    assert isinstance(return_local, ReturnLocalNode)


def test_nested_ifs_and_non_inlined_blocks(cgenc, mgenc):
    add_field(cgenc, "field")
    seq = parse_method(
        mgenc,
        """
        test: arg = (
          | a |
          a := 1.
          true ifTrue: [
            | e |
            e := 0.
            [ a := 1. a ].
            false ifFalse: [
              | h |
              h := 1.
              [ h + a + e ].
              ^ h ] ].

          [ a ]
        )""",
    )

    if_true = seq._exprs[1]
    assert isinstance(if_true, IfInlinedNode)

    block_node = if_true._body_expr._exprs[1]
    method_expr = block_node._value.invokable.expr_or_sequence._exprs
    write = method_expr[0]
    assert write._context_level == 1
    assert write._var._name == "a"
    assert write._var.idx == 0

    if_false = if_true._body_expr._exprs[2]
    assert isinstance(if_false, IfInlinedNode)

    body_if_false = if_false._body_expr._exprs

    write = body_if_false[0]
    assert isinstance(write, UninitializedWriteNode)
    assert write._context_level == 0
    assert write._var._name == "h"

    return_local = body_if_false[2]
    assert isinstance(return_local, ReturnLocalNode)


def test_nested_non_inlined_blocks(cgenc, mgenc):
    add_field(cgenc, "field")
    ast = parse_method(
        mgenc,
        """
        test: a = ( | b |
          true ifFalse: [ | c |
            a. b. c.
            [:d |
              a. b. c. d.
              [:e |
                a. b. c. d. e ] ] ]
        )""",
    )

    if_false = ast._exprs[0]
    assert isinstance(if_false, IfInlinedNode)

    block_seq = if_false._body_expr._exprs[3]._value.invokable.expr_or_sequence
    read_a = block_seq._exprs[0]
    assert read_a._context_level == 1
    assert read_a.var._name == "a"
    assert read_a.var.idx == 1

    read_b = block_seq._exprs[1]
    assert read_b._context_level == 1
    assert read_b.var._name == "b"
    assert read_b.var.idx == 0

    block_seq = block_seq._exprs[4]._value.invokable.expr_or_sequence
    read_a = block_seq._exprs[0]
    assert read_a._context_level == 2
    assert read_a.var._name == "a"
    assert read_a.var.idx == 1

    read_b = block_seq._exprs[1]
    assert read_b._context_level == 2
    assert read_b.var._name == "b"
    assert read_b.var.idx == 0


@pytest.mark.parametrize(
    "sel1,sel2,expected_bool,unexpected_bool",
    [
        ("ifTrue:", "ifFalse:", trueObject, falseObject),
        ("ifFalse:", "ifTrue:", falseObject, trueObject),
    ],
)
def test_if_true_if_false_return(mgenc, sel1, sel2, expected_bool, unexpected_bool):
    seq = parse_method(
        mgenc,
        """
        test: arg1 with: arg2 = (
            #start.
            ^ self method SEL1 [ ^ arg1 ] SEL2 [ arg2 ]
        )""".replace(
            "SEL1", sel1
        ).replace(
            "SEL2", sel2
        ),
    )

    assert isinstance(seq._exprs[1], IfElseInlinedNode)
    if_node = seq._exprs[1]
    assert if_node._expected_bool is expected_bool
    assert if_node._not_expected_bool is unexpected_bool


@pytest.mark.parametrize(
    "while_sel,expected_bool,unexpected_bool",
    [
        ("whileTrue:", trueObject, falseObject),
        ("whileFalse:", falseObject, trueObject),
    ],
)
def test_while_inlining(mgenc, while_sel, expected_bool, unexpected_bool):
    seq = parse_method(
        mgenc,
        """
        test: arg1 with: arg2 = (
            [ arg1 ] WHILE [ arg2 ]
        )""".replace(
            "WHILE", while_sel
        ),
    )

    assert isinstance(seq._exprs[0], WhileInlinedNode)
    while_node = seq._exprs[0]
    assert while_node._expected_bool is expected_bool
    assert while_node._not_expected_bool is unexpected_bool


def test_block_block_inlined_self(cgenc, mgenc):
    add_field(cgenc, "field")
    ast = parse_method(
        mgenc,
        """
        test = (
          [:a |
            [:b |
              b ifTrue: [ field := field + 1 ] ] ]
        )""",
    )
    block_a = ast._exprs[0]._value.invokable.expr_or_sequence
    block_b_if_true = block_a._value.invokable.expr_or_sequence

    read_node = block_b_if_true._condition_expr
    assert read_node._context_level == 0
    assert read_node.var._name == "b"
    assert read_node.var.idx == 1

    write_node = block_b_if_true._body_expr
    assert isinstance(write_node, FieldIncrementNode)
    assert write_node.field_idx == 0

    assert write_node._self_exp._frame_idx == FRAME_AND_INNER_RCVR_IDX
    assert write_node._self_exp._context_level == 2


def test_to_do_block_block_inlined_self(cgenc, mgenc):
    add_field(cgenc, "field")
    ast = parse_method(
        mgenc,
        """
        test = (
          | l1 l2 |
          1 to: 2 do: [:a |
            l1 do: [:b |
              b ifTrue: [ l2 := l2 + 1 ] ] ]
        )""",
    )
    block_a = ast._exprs[0]._do_expr
    block_b_if_true = block_a._arg_exprs[0]._value.invokable.expr_or_sequence

    read_node = block_b_if_true._condition_expr
    assert read_node._context_level == 0
    assert read_node.var._name == "b"
    assert read_node.var.idx == 1

    write_node = block_b_if_true._body_expr
    assert write_node._context_level == 1
    assert write_node._var._name == "l2"
    assert write_node._var.idx == 1

    assert isinstance(write_node._value_expr, IntIncrementNode)
    read_l2_node = write_node._value_expr._rcvr_expr
    assert read_l2_node._context_level == 1
    assert read_l2_node.var._name == "l2"
    assert read_l2_node.var.idx == 1


@pytest.mark.parametrize("and_sel", ["and:", "&&"])
def test_inlining_of_and(mgenc, and_sel):
    ast = parse_method(
        mgenc, "test = ( true AND_SEL [ #val ] )".replace("AND_SEL", and_sel)
    )

    assert isinstance(ast._exprs[0], AndInlinedNode)


def test_field_read_inlining(cgenc, mgenc):
    add_field(cgenc, "field")
    ast = parse_method(mgenc, "test = ( true and: [ field ] )")

    assert isinstance(ast._exprs[0], AndInlinedNode)
    and_expr = ast._exprs[0]
    assert isinstance(and_expr._arg_expr, FieldReadNode)


@pytest.mark.parametrize("or_sel", ["or:", "||"])
def test_inlining_of_or(mgenc, or_sel):
    ast = parse_method(
        mgenc, "test = ( true OR_SEL [ #val ] )".replace("OR_SEL", or_sel)
    )

    assert isinstance(ast._exprs[0], OrInlinedNode)


def test_inlining_of_to_do(mgenc):
    ast = parse_method(mgenc, "test = ( 1 to: 2 do: [:i | i ] )")

    assert isinstance(ast._exprs[0], ToDoInlined)
    to_do = ast._exprs[0]
    assert to_do._idx_var._name == "i"
