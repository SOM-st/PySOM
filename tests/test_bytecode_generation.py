# pylint: disable=redefined-outer-name
from collections import deque
import pytest
from rlib.string_stream import StringStream

from som.compiler.bc.disassembler import dump_method
from som.compiler.bc.method_generation_context import MethodGenerationContext
from som.compiler.bc.parser import Parser
from som.compiler.class_generation_context import ClassGenerationContext
from som.interp_type import is_ast_interpreter
from som.interpreter.bc.bytecodes import Bytecodes, bytecode_length, bytecode_as_str
from som.vm.current import current_universe
from som.vm.symbols import symbol_for

pytestmark = pytest.mark.skipif(  # pylint: disable=invalid-name
    is_ast_interpreter(), reason="Tests are specific to bytecode interpreter"
)


def add_field(cgenc, name):
    cgenc.add_instance_field(symbol_for(name))


def dump(mgenc):
    dump_method(mgenc, "")


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


@pytest.fixture
def bgenc(cgenc, mgenc):
    mgenc.signature = symbol_for("test")
    bgenc = MethodGenerationContext(current_universe, cgenc, mgenc)
    return bgenc


def method_to_bytecodes(mgenc, source, dump_bytecodes=False):
    parser = Parser(StringStream(source.strip()), "test", current_universe)
    parser.method(mgenc)
    if dump_bytecodes:
        dump(mgenc)
    return mgenc.get_bytecodes()


def block_to_bytecodes(bgenc, source):
    parser = Parser(StringStream(source), "test", current_universe)

    parser.nested_block(bgenc)
    return bgenc.get_bytecodes()


class BC(object):
    def __init__(self, bytecode, arg1=None, arg2=None, note=None):
        self.bytecode = bytecode
        self.arg1 = arg1
        self.arg2 = arg2
        self.note = note


def check(actual, expected):
    expected_q = deque(expected)
    i = 0
    while i < len(actual) and expected_q:
        actual_bc = actual[i]
        bc_length = bytecode_length(actual_bc)

        expected_bc = expected_q[0]
        if isinstance(expected_bc, tuple):
            if expected_bc[0] == i:
                expected_bc = expected_bc[1]
            else:
                assert expected_bc[0] > i
                i += bc_length
                continue

        if isinstance(expected_bc, BC):
            assert actual_bc == expected_bc.bytecode, (
                "Bytecode "
                + str(i)
                + " expected "
                + bytecode_as_str(expected_bc.bytecode)
                + " but got "
                + bytecode_as_str(actual_bc)
            )
            if expected_bc.arg1 is not None:
                assert actual[i + 1] == expected_bc.arg1, (
                    "Bytecode "
                    + str(i)
                    + " expected "
                    + bytecode_as_str(expected_bc.bytecode)
                    + "("
                    + str(expected_bc.arg1)
                    + ", "
                    + str(expected_bc.arg2)
                    + ") but got "
                    + bytecode_as_str(actual_bc)
                    + "("
                    + str(actual[i + 1])
                    + ", "
                    + str(actual[i + 2])
                    + ")"
                )
            if expected_bc.arg2 is not None:
                assert actual[i + 2] == expected_bc.arg2
        else:
            assert actual_bc == expected_bc, (
                "Bytecode "
                + str(i)
                + " expected "
                + bytecode_as_str(expected_bc)
                + " but got "
                + bytecode_as_str(actual_bc)
            )
        expected_q.popleft()

        i += bc_length

    assert len(expected_q) == 0


@pytest.mark.parametrize(
    "operator,bytecode",
    [
        ("+", Bytecodes.inc),
        ("-", Bytecodes.dec),
    ],
)
def test_inc_dec_bytecodes(mgenc, operator, bytecode):
    bytecodes = method_to_bytecodes(mgenc, "test = ( 1 OP 1 )".replace("OP", operator))

    assert len(bytecodes) == 3
    check(bytecodes, [Bytecodes.push_1, bytecode, Bytecodes.return_self])


def test_empty_method_returns_self(mgenc):
    bytecodes = method_to_bytecodes(mgenc, "test = ( )")

    assert len(bytecodes) == 1
    check(bytecodes, [Bytecodes.return_self])


def test_explicit_return_self(mgenc):
    bytecodes = method_to_bytecodes(mgenc, "test = ( ^ self )")

    assert len(bytecodes) == 1
    check(bytecodes, [Bytecodes.return_self])


def test_dup_pop_argument_pop(mgenc):
    bytecodes = method_to_bytecodes(mgenc, "test: arg = ( arg := 1. ^ self )")

    assert len(bytecodes) == 5
    check(bytecodes, [Bytecodes.push_1, Bytecodes.pop_argument, Bytecodes.return_self])


def test_dup_pop_argument_pop_implicit_return_self(mgenc):
    bytecodes = method_to_bytecodes(mgenc, "test: arg = ( arg := 1 )")

    assert len(bytecodes) == 5
    check(bytecodes, [Bytecodes.push_1, Bytecodes.pop_argument, Bytecodes.return_self])


def test_dup_pop_local_pop(mgenc):
    bytecodes = method_to_bytecodes(mgenc, "test = ( | local | local := 1. ^ self )")

    assert len(bytecodes) == 5
    assert Bytecodes.push_1 == bytecodes[0]
    assert Bytecodes.pop_local == bytecodes[1]
    assert Bytecodes.return_self == bytecodes[4]


def test_dup_pop_field_0_pop(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test = ( field := 1. ^ self )")

    assert len(bytecodes) == 3
    assert Bytecodes.push_1 == bytecodes[0]
    assert Bytecodes.pop_field_0 == bytecodes[1]
    assert Bytecodes.return_self == bytecodes[2]


def test_dup_pop_field_pop(cgenc, mgenc):
    add_field(cgenc, "a")
    add_field(cgenc, "b")
    add_field(cgenc, "c")
    add_field(cgenc, "d")
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test = ( field := 1. ^ self )")

    assert len(bytecodes) == 5
    check(bytecodes, [Bytecodes.push_1, Bytecodes.pop_field, Bytecodes.return_self])


def test_dup_pop_field_return_self(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test: val = ( field := val )")

    assert len(bytecodes) == 5
    check(
        bytecodes,
        [Bytecodes.push_argument, Bytecodes.pop_field_0, Bytecodes.return_self],
    )


def test_dup_pop_field_n_return_self(cgenc, mgenc):
    add_field(cgenc, "a")
    add_field(cgenc, "b")
    add_field(cgenc, "c")
    add_field(cgenc, "d")
    add_field(cgenc, "e")
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test: value = ( field := value )")

    assert len(bytecodes) == 7
    check(
        bytecodes, [Bytecodes.push_argument, Bytecodes.pop_field, Bytecodes.return_self]
    )


def test_send_dup_pop_field_return_local(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test = ( ^ field := self method )")

    assert len(bytecodes) == 8
    check(
        bytecodes,
        [
            Bytecodes.push_argument,
            Bytecodes.send_1,
            Bytecodes.dup,
            Bytecodes.pop_field_0,
            Bytecodes.return_local,
        ],
    )


def test_send_dup_pop_field_return_local_period(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test = ( ^ field := self method. )")

    assert len(bytecodes) == 8
    check(
        bytecodes,
        [
            Bytecodes.push_argument,
            Bytecodes.send_1,
            Bytecodes.dup,
            Bytecodes.pop_field_0,
            Bytecodes.return_local,
        ],
    )


@pytest.mark.parametrize(
    "literal,bytecode",
    [
        ("0", Bytecodes.push_0),
        ("1", Bytecodes.push_1),
        ("-10", Bytecodes.push_constant_2),
        ("3333", Bytecodes.push_constant_2),
        ("'str'", Bytecodes.push_constant_2),
        ("#sym", Bytecodes.push_constant_2),
        ("1.1", Bytecodes.push_constant_2),
        ("-2342.234", Bytecodes.push_constant_2),
        ("true", Bytecodes.push_constant_2),
        ("false", Bytecodes.push_constant_2),
        ("nil", Bytecodes.push_nil),
        ("SomeGlobal", Bytecodes.push_global),
        ("[]", Bytecodes.push_block_no_ctx),
        ("[ self ]", Bytecodes.push_block),
    ],
)
def test_if_true_with_literal_return(mgenc, literal, bytecode):
    source = """
        test = (
            self method ifTrue: [ LITERAL ].
        )""".replace(
        "LITERAL", literal
    )
    bytecodes = method_to_bytecodes(mgenc, source)

    length = bytecode_length(bytecode)

    assert len(bytecodes) == 10 + length
    check(
        bytecodes,
        [
            Bytecodes.push_argument,
            Bytecodes.send_1,
            Bytecodes.jump_on_false_top_nil,
            bytecode,
            Bytecodes.pop,
            Bytecodes.return_self,
        ],
    )


@pytest.mark.parametrize(
    "literal,bytecode",
    [
        ("0", Bytecodes.push_0),
        ("1", Bytecodes.push_1),
        ("-10", Bytecodes.push_constant),
        ("3333", Bytecodes.push_constant),
        ("'str'", Bytecodes.push_constant),
        ("#sym", Bytecodes.push_constant),
        ("1.1", Bytecodes.push_constant),
        ("-2342.234", Bytecodes.push_constant),
        ("true", Bytecodes.push_constant),
        ("false", Bytecodes.push_constant),
        ("nil", Bytecodes.push_nil),
        ("SomeGlobal", Bytecodes.push_global),
        ("[]", Bytecodes.push_block_no_ctx),
        ("[ self ]", Bytecodes.push_block),
    ],
)
def test_if_true_with_something_and_literal_return(mgenc, literal, bytecode):
    # This test is different from the previous one, because the block
    # method won't be recognized as being trivial
    source = """
        test = (
            self method ifTrue: [ #fooBarNonTrivialBlock. LITERAL ].
        )""".replace(
        "LITERAL", literal
    )
    bytecodes = method_to_bytecodes(mgenc, source)

    length = bytecode_length(bytecode)

    assert len(bytecodes) == 12 + length
    check(
        bytecodes,
        [
            Bytecodes.push_argument,
            Bytecodes.send_1,
            Bytecodes.jump_on_false_top_nil,
            Bytecodes.push_constant_2,
            Bytecodes.pop,
            bytecode,
            Bytecodes.pop,
            Bytecodes.return_self,
        ],
    )


@pytest.mark.parametrize(
    "if_selector,jump_bytecode",
    [
        ("ifTrue:", Bytecodes.jump_on_false_top_nil),
        ("ifFalse:", Bytecodes.jump_on_true_top_nil),
    ],
)
def test_if_arg(mgenc, if_selector, jump_bytecode):
    bytecodes = method_to_bytecodes(
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

    assert len(bytecodes) == 17
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            Bytecodes.pop,
            Bytecodes.push_argument,
            Bytecodes.send_1,
            BC(jump_bytecode, 6, note="jump offset"),
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.pop,
            Bytecodes.push_constant,
            Bytecodes.return_self,
        ],
    )


def test_keyword_if_true_arg(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg = (
            #start.
            (self key: 5) ifTrue: [ arg ].
            #end
        )""",
    )

    assert len(bytecodes) == 18
    check(
        bytecodes,
        [
            (6, Bytecodes.send_2),
            BC(Bytecodes.jump_on_false_top_nil, 6, note="jump offset"),
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.pop,
            Bytecodes.push_constant,
        ],
    )


def test_if_true_and_inc_field(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg = (
            #start.
            (self key: 5) ifTrue: [ field := field + 1 ].
            #end
        )""",
    )

    assert len(bytecodes) == 18
    check(
        bytecodes,
        [
            (6, Bytecodes.send_2),
            BC(Bytecodes.jump_on_false_top_nil, 6, note="jump offset"),
            Bytecodes.inc_field_push,
            Bytecodes.pop,
            Bytecodes.push_constant,
        ],
    )


def test_if_true_and_inc_arg(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg = (
            #start.
            (self key: 5) ifTrue: [ arg + 1 ].
            #end
        )""",
    )

    assert len(bytecodes) == 19
    check(
        bytecodes,
        [
            (6, Bytecodes.send_2),
            BC(Bytecodes.jump_on_false_top_nil, 7, note="jump offset"),
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.inc,
            Bytecodes.pop,
            Bytecodes.push_constant,
        ],
    )


@pytest.mark.parametrize(
    "if_selector,jump_bytecode",
    [
        ("ifTrue:", Bytecodes.jump_on_false_top_nil),
        ("ifFalse:", Bytecodes.jump_on_true_top_nil),
    ],
)
def test_if_return_non_local(mgenc, if_selector, jump_bytecode):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg = (
            #start.
            self method IF_SELECTOR [ ^ arg ].
            #end
        )""".replace(
            "IF_SELECTOR", if_selector
        ),
    )

    assert len(bytecodes) == 18
    check(
        bytecodes,
        [
            (5, Bytecodes.send_1),
            BC(jump_bytecode, 7, note="jump offset"),
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.return_local,
            Bytecodes.pop,
        ],
    )


def test_nested_ifs(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(
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

    assert len(bytecodes) == 16
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            BC(Bytecodes.jump_on_false_top_nil, 14, note="jump offset"),
            (5, Bytecodes.jump_on_true_top_nil),
            Bytecodes.push_field_0,
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.send_2,
            Bytecodes.return_local,
            Bytecodes.return_self,
        ],
    )


def test_nested_ifs_and_locals(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(
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

    assert len(bytecodes) == 54
    check(
        bytecodes,
        [
            BC(Bytecodes.push_local, 1, 0),
            BC(Bytecodes.pop_local, 0, 0),
            (7, BC(Bytecodes.jump_on_false_top_nil, 46)),
            (12, BC(Bytecodes.pop_local, 4, 0)),
            (17, BC(Bytecodes.pop_local, 2, 0)),
            (22, BC(Bytecodes.jump_on_true_top_nil, 31)),
            (26, BC(Bytecodes.pop_local, 7, 0)),
            (47, BC(Bytecodes.push_local, 3, 0)),
        ],
    )


def test_nested_ifs_and_non_inlined_blocks(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(
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

    assert len(bytecodes) == 35
    check(
        bytecodes,
        [
            (4, Bytecodes.push_constant_1),
            BC(Bytecodes.jump_on_false_top_nil, 26),
            (9, BC(Bytecodes.pop_local, 1, 0, note="local e")),
            (17, BC(Bytecodes.jump_on_true_top_nil, 14)),
            (21, BC(Bytecodes.pop_local, 2, 0, note="local h")),
        ],
    )

    check(
        mgenc.get_constant(12).get_bytecodes(),
        [(1, BC(Bytecodes.pop_local, 0, 1, note="local a"))],
    )

    check(
        mgenc.get_constant(24).get_bytecodes(),
        [
            BC(Bytecodes.push_local, 2, 1, note="local h"),
            BC(Bytecodes.push_local, 0, 1, note="local a"),
            (8, BC(Bytecodes.push_local, 1, 1, note="local e")),
        ],
    )

    check(
        mgenc.get_constant(32).get_bytecodes(),
        [BC(Bytecodes.push_local, 0, 1, note="local a")],
    )


def test_nested_non_inlined_blocks(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(
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

    assert len(bytecodes) == 19
    check(
        bytecodes,
        [
            (1, BC(Bytecodes.jump_on_true_top_nil, 17)),
            BC(Bytecodes.push_argument, 1, 0, note="arg a"),
            (8, BC(Bytecodes.push_local, 0, 0, note="local b")),
            (12, BC(Bytecodes.push_local, 1, 0, note="local c")),
        ],
    )

    block_method = mgenc.get_constant(16)
    check(
        block_method.get_bytecodes(),
        [
            BC(Bytecodes.push_argument, 1, 1, note="arg a"),
            (4, BC(Bytecodes.push_local, 0, 1, note="local b")),
            (8, BC(Bytecodes.push_local, 1, 1, note="local c")),
            (12, BC(Bytecodes.push_argument, 1, 0, note="arg d")),
        ],
    )

    block_method = block_method.get_constant(16)
    check(
        block_method.get_bytecodes(),
        [
            BC(Bytecodes.push_argument, 1, 2, note="arg a"),
            (4, BC(Bytecodes.push_local, 0, 2, note="local b")),
            (8, BC(Bytecodes.push_local, 1, 2, note="local c")),
            (12, BC(Bytecodes.push_argument, 1, 1, note="arg d")),
            (16, BC(Bytecodes.push_argument, 1, 0, note="arg e")),
        ],
    )


def test_block_if_true_arg(bgenc):
    bytecodes = block_to_bytecodes(
        bgenc,
        """
        [:arg | #start.
            self method ifTrue: [ arg ].
            #end
        ]""",
    )

    assert len(bytecodes) == 17
    check(
        bytecodes,
        [
            (5, Bytecodes.send_1),
            BC(Bytecodes.jump_on_false_top_nil, 6),
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.pop,
            Bytecodes.push_constant,
        ],
    )


def test_block_if_true_method_arg(mgenc, bgenc):
    mgenc.add_argument("arg", None, None)
    bytecodes = block_to_bytecodes(
        bgenc,
        """
        [ #start.
            self method ifTrue: [ arg ].
            #end
        ]""",
    )

    assert len(bytecodes) == 17
    check(
        bytecodes,
        [
            (7, BC(Bytecodes.jump_on_false_top_nil, 6)),
            BC(Bytecodes.push_argument, 1, 1),
            Bytecodes.pop,
            Bytecodes.push_constant,
        ],
    )


def test_if_true_if_false_arg(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg1 with: arg2 = (
            #start.
            self method ifTrue: [ arg1 ] ifFalse: [ arg2 ].
            #end
        )""",
    )

    assert len(bytecodes) == 23
    check(
        bytecodes,
        [
            (7, BC(Bytecodes.jump_on_false_pop, 9)),
            BC(Bytecodes.push_argument, 1, 0),
            BC(Bytecodes.jump, 6),
            BC(Bytecodes.push_argument, 2, 0),
            Bytecodes.pop,
        ],
    )


def test_if_true_if_false_nlr_arg1(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg1 with: arg2 = (
            #start.
            self method ifTrue: [ ^ arg1 ] ifFalse: [ arg2 ].
            #end
        )""",
    )

    assert len(bytecodes) == 24
    check(
        bytecodes,
        [
            (7, BC(Bytecodes.jump_on_false_pop, 10)),
            BC(Bytecodes.push_argument, 1, 0),
            Bytecodes.return_local,
            BC(Bytecodes.jump, 6),
            BC(Bytecodes.push_argument, 2, 0),
            Bytecodes.pop,
        ],
    )


def test_if_true_if_false_nlr_arg2(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg1 with: arg2 = (
            #start.
            self method ifTrue: [ arg1 ] ifFalse: [ ^ arg2 ].
            #end
        )""",
    )

    assert len(bytecodes) == 24
    check(
        bytecodes,
        [
            (7, BC(Bytecodes.jump_on_false_pop, 9)),
            BC(Bytecodes.push_argument, 1, 0),
            BC(Bytecodes.jump, 7),
            BC(Bytecodes.push_argument, 2, 0),
            Bytecodes.return_local,
            Bytecodes.pop,
        ],
    )


@pytest.mark.parametrize(
    "sel1,sel2,jump_bytecode",
    [
        ("ifTrue:", "ifFalse:", Bytecodes.jump_on_false_pop),
        ("ifFalse:", "ifTrue:", Bytecodes.jump_on_true_pop),
    ],
)
def test_if_true_if_false_return(mgenc, sel1, sel2, jump_bytecode):
    bytecodes = method_to_bytecodes(
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

    assert len(bytecodes) == 21
    check(
        bytecodes,
        [
            (7, BC(jump_bytecode, 10)),
            (14, BC(Bytecodes.jump, 6)),
        ],
    )


def test_if_push_constant_same(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test = (
          #a. #b. #c. #d.
          true ifFalse: [ #a. #b. #c. #d. ]
        )""",
    )

    assert len(bytecodes) == 23
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            (2, Bytecodes.push_constant_1),
            (4, Bytecodes.push_constant_2),
            (6, BC(Bytecodes.push_constant, 3)),
            (11, BC(Bytecodes.jump_on_true_top_nil, 11)),
            (14, Bytecodes.push_constant_0),
            (16, Bytecodes.push_constant_1),
            (18, Bytecodes.push_constant_2),
            (20, BC(Bytecodes.push_constant, 3)),
        ],
    )


def test_if_push_constant_different(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test = (
          #a. #b. #c. #d.
          true ifFalse: [ #e. #f. #g. #h. ]
        )""",
    )

    assert len(bytecodes) == 26
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            (2, Bytecodes.push_constant_1),
            (4, Bytecodes.push_constant_2),
            (6, BC(Bytecodes.push_constant, 3)),
            (11, BC(Bytecodes.jump_on_true_top_nil, 14)),
            (14, BC(Bytecodes.push_constant, 6)),
            (17, BC(Bytecodes.push_constant, 7)),
            (20, BC(Bytecodes.push_constant, 8)),
            (23, BC(Bytecodes.push_constant, 9)),
        ],
    )


def test_if_inline_and_constant_bc_length(mgenc):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test = (
          #a. #b. #c.
          true ifTrue: [
            true ifFalse: [ #e. #f. #g ] ]
        )""",
    )

    assert Bytecodes.jump_on_true_top_nil == bytecodes[13]
    assert bytecodes[14] == 11, (
        "jump offset, should point to correct bytecode"
        + " and not be affected by changing length of bytecodes in the block"
    )


def test_block_dup_pop_argument_pop_return_arg(bgenc):
    bytecodes = block_to_bytecodes(bgenc, "[:arg | arg := 1. arg ]")

    assert len(bytecodes) == 8
    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.pop_argument,
            (4, Bytecodes.push_argument),
            Bytecodes.return_local,
        ],
    )


def test_block_dup_pop_argument_pop_implicit_return(bgenc):
    bytecodes = block_to_bytecodes(bgenc, "[:arg | arg := 1 ]")

    assert len(bytecodes) == 6
    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.dup,
            Bytecodes.pop_argument,
            Bytecodes.return_local,
        ],
    )


def test_block_dup_pop_argument_pop_implicit_return_dot(bgenc):
    bytecodes = block_to_bytecodes(bgenc, "[:arg | arg := 1. ]")

    assert len(bytecodes) == 6
    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.dup,
            Bytecodes.pop_argument,
            Bytecodes.return_local,
        ],
    )


def test_block_dup_pop_local_return_local(bgenc):
    bytecodes = block_to_bytecodes(bgenc, "[| local | local := 1 ]")

    assert len(bytecodes) == 6
    check(
        bytecodes,
        [Bytecodes.push_1, Bytecodes.dup, Bytecodes.pop_local, Bytecodes.return_local],
    )


def test_block_dup_pop_field_return_local(cgenc, bgenc):
    add_field(cgenc, "field")
    bytecodes = block_to_bytecodes(bgenc, "[ field := 1 ]")

    assert len(bytecodes) == 6
    check(
        bytecodes,
        [Bytecodes.push_1, Bytecodes.dup, Bytecodes.pop_field, Bytecodes.return_local],
    )


def test_block_dup_pop_field_return_local_dot(cgenc, bgenc):
    add_field(cgenc, "field")
    bytecodes = block_to_bytecodes(bgenc, "[ field := 1. ]")

    assert len(bytecodes) == 6
    check(
        bytecodes,
        [Bytecodes.push_1, Bytecodes.dup, Bytecodes.pop_field, Bytecodes.return_local],
    )


@pytest.mark.parametrize(
    "if_selector,jump_bytecode",
    [
        ("ifTrue:", Bytecodes.jump_on_false_top_nil),
        ("ifFalse:", Bytecodes.jump_on_true_top_nil),
    ],
)
def test_block_if_return_non_local(bgenc, if_selector, jump_bytecode):
    bytecodes = block_to_bytecodes(
        bgenc,
        """
        [:arg |
            #start.
            self method IF_SELECTOR [ ^ arg ].
            #end
        ]""".replace(
            "IF_SELECTOR", if_selector
        ),
    )

    assert len(bytecodes) == 19
    check(
        bytecodes,
        [
            (5, Bytecodes.send_1),
            BC(jump_bytecode, 8),
            BC(Bytecodes.push_argument, 1, 0),
            BC(Bytecodes.return_non_local, 1),
            Bytecodes.pop,
        ],
    )


@pytest.mark.parametrize(
    "selector,jump_bytecode",
    [
        ("whileTrue:", Bytecodes.jump_on_false_pop),
        ("whileFalse:", Bytecodes.jump_on_true_pop),
    ],
)
def test_while_inlining(mgenc, selector, jump_bytecode):
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test: arg = (
            #start.
            [ true ] SELECTOR [ arg ].
            #end
        )""".replace(
            "SELECTOR", selector
        ),
    )

    assert len(bytecodes) == 19
    check(
        bytecodes,
        [
            (2, Bytecodes.push_constant),
            jump_bytecode,
            Bytecodes.push_argument,
            Bytecodes.pop,
            BC(Bytecodes.jump_backward, 9),
            Bytecodes.push_nil,
            Bytecodes.pop,
        ],
    )


def test_inlining_while_loop_with_expanding_branches(mgenc):
    """
    This test checks whether the jumps in the while loop are correct after it got inlined.
    The challenge here is
    """
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test = (
          #const0. #const1. #const2.
          0 ifTrue: [
            [ #const3. #const4. #const5 ]
               whileTrue: [
                 #const6. #const7. #const8 ]
          ].
          ^ #end
        )
        """,
    )

    assert len(bytecodes) == 38
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            Bytecodes.pop,
            Bytecodes.push_constant_1,
            Bytecodes.pop,
            Bytecodes.push_constant_2,
            Bytecodes.pop,
            Bytecodes.push_0,
            BC(
                Bytecodes.jump_on_false_top_nil,
                27,
                note="jump offset, to jump to the pop BC after the if/right before the push #end",
            ),
            Bytecodes.push_constant,
            Bytecodes.pop,
            Bytecodes.push_constant,
            Bytecodes.pop,
            Bytecodes.push_constant,
            BC(
                Bytecodes.jump_on_false_pop,
                15,
                note="jump offset, jump to push_nil as result of whileTrue",
            ),
            Bytecodes.push_constant,
            Bytecodes.pop,
            Bytecodes.push_constant,
            Bytecodes.pop,
            Bytecodes.push_constant,
            Bytecodes.pop,
            BC(
                Bytecodes.jump_backward,
                20,
                note="jump offset, jump back to the first push constant "
                + "in the condition, pushing const3",
            ),
            Bytecodes.push_nil,
            Bytecodes.pop,
        ],
    )


def test_inlining_while_loop_with_contracting_branches(mgenc):
    """
    This test checks whether the jumps in the while loop are correct after it got inlined.
    The challenge here is
    """
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test = (
          0 ifTrue: [
            [ ^ 1 ]
               whileTrue: [
                 ^ 0 ]
          ].
          ^ #end
        )
        """,
    )

    assert len(bytecodes) == 19
    check(
        bytecodes,
        [
            Bytecodes.push_0,
            BC(
                Bytecodes.jump_on_false_top_nil,
                15,
                note="jump offset to jump to the pop after the if, before pushing #end",
            ),
            Bytecodes.push_1,
            Bytecodes.return_local,
            BC(
                Bytecodes.jump_on_false_pop,
                9,
                note="jump offset, jump to push_nil as result of whileTrue",
            ),
            Bytecodes.push_0,
            Bytecodes.return_local,
            Bytecodes.pop,
            BC(
                Bytecodes.jump_backward,
                8,
                note="jump offset, to the push_1 of the condition",
            ),
            Bytecodes.push_nil,
            Bytecodes.pop,
        ],
    )


@pytest.mark.parametrize(
    "source,bytecode",
    [
        ("0", Bytecodes.push_0),
        ("1", Bytecodes.push_1),
        ("-10", Bytecodes.push_constant_2),
        ("3333", Bytecodes.push_constant_2),
        ("'str'", Bytecodes.push_constant_2),
        ("#sym", Bytecodes.push_constant_2),
        ("1.1", Bytecodes.push_constant_2),
        ("-2342.234", Bytecodes.push_constant_2),
        ("true", Bytecodes.push_constant_0),
        ("false", Bytecodes.push_constant_2),
        ("nil", Bytecodes.push_nil),
        ("Nil", Bytecodes.push_global),
        ("UnknownGlobal", Bytecodes.push_global),
        ("[]", Bytecodes.push_block_no_ctx),
    ],
)
def test_trivial_method_inlining(mgenc, source, bytecode):
    bytecodes = method_to_bytecodes(mgenc, "test = ( true ifTrue: [ " + source + " ] )")
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            Bytecodes.jump_on_false_top_nil,
            bytecode,
            Bytecodes.return_self,
        ],
    )


@pytest.mark.parametrize("field_num", range(0, 7))
def test_inc_field(cgenc, mgenc, field_num):
    add_field(cgenc, "field0")
    add_field(cgenc, "field1")
    add_field(cgenc, "field2")
    add_field(cgenc, "field3")
    add_field(cgenc, "field4")
    add_field(cgenc, "field5")
    add_field(cgenc, "field6")

    field_name = "field" + str(field_num)
    bytecodes = method_to_bytecodes(
        mgenc, "test = ( " + field_name + " := " + field_name + " + 1 )"
    )

    check(
        bytecodes,
        [
            BC(Bytecodes.inc_field, field_num, 0),
            Bytecodes.return_self,
        ],
    )


@pytest.mark.parametrize("field_num", range(0, 7))
def test_inc_field_non_trivial(cgenc, mgenc, field_num):
    add_field(cgenc, "field0")
    add_field(cgenc, "field1")
    add_field(cgenc, "field2")
    add_field(cgenc, "field3")
    add_field(cgenc, "field4")
    add_field(cgenc, "field5")
    add_field(cgenc, "field6")

    field_name = "field" + str(field_num)
    bytecodes = method_to_bytecodes(
        mgenc, "test = ( 1. " + field_name + " := " + field_name + " + 1. 2 )"
    )
    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.pop,
            BC(Bytecodes.inc_field, field_num, 0),
            Bytecodes.push_constant_1,
            Bytecodes.return_self,
        ],
    )


@pytest.mark.parametrize("field_num", range(0, 7))
def test_return_inc_field(cgenc, mgenc, field_num):
    add_field(cgenc, "field0")
    add_field(cgenc, "field1")
    add_field(cgenc, "field2")
    add_field(cgenc, "field3")
    add_field(cgenc, "field4")
    add_field(cgenc, "field5")
    add_field(cgenc, "field6")

    field_name = "field" + str(field_num)
    bytecodes = method_to_bytecodes(
        mgenc, "test = ( #foo. ^ " + field_name + " := " + field_name + " + 1 )"
    )
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            Bytecodes.pop,
            BC(Bytecodes.inc_field_push, field_num, 0),
            Bytecodes.return_local,
        ],
    )


@pytest.mark.parametrize("field_num", range(0, 7))
def test_return_inc_field_from_block(cgenc, bgenc, field_num):
    add_field(cgenc, "field0")
    add_field(cgenc, "field1")
    add_field(cgenc, "field2")
    add_field(cgenc, "field3")
    add_field(cgenc, "field4")
    add_field(cgenc, "field5")
    add_field(cgenc, "field6")

    field_name = "field" + str(field_num)
    bytecodes = block_to_bytecodes(
        bgenc, "[ #foo. " + field_name + " := " + field_name + " + 1 ]"
    )

    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            Bytecodes.pop,
            BC(Bytecodes.inc_field_push, field_num, 1),
            Bytecodes.return_local,
        ],
    )


@pytest.mark.parametrize(
    "field_num,bytecode",
    [
        (0, Bytecodes.return_field_0),
        (1, Bytecodes.return_field_1),
        (2, Bytecodes.return_field_2),
        (3, BC(Bytecodes.push_field, 3)),
        (4, BC(Bytecodes.push_field, 4)),
    ],
)
def test_return_field(cgenc, mgenc, field_num, bytecode):
    add_field(cgenc, "field0")
    add_field(cgenc, "field1")
    add_field(cgenc, "field2")
    add_field(cgenc, "field3")
    add_field(cgenc, "field4")
    add_field(cgenc, "field5")
    add_field(cgenc, "field6")

    field_name = "field" + str(field_num)
    bytecodes = method_to_bytecodes(mgenc, "test = ( 1. ^ " + field_name + " )")

    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.pop,
            bytecode,
        ],
    )


@pytest.mark.parametrize("and_sel", ["and:", "&&"])
def test_inlining_of_and(mgenc, and_sel):
    bytecodes = method_to_bytecodes(
        mgenc, "test = ( true AND_SEL [ #val ] )".replace("AND_SEL", and_sel)
    )

    assert len(bytecodes) == 11
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            BC(Bytecodes.jump_on_false_pop, 7),
            # true branch
            Bytecodes.push_constant_2,  # push the `#val`
            BC(Bytecodes.jump, 5),
            # false branch, jump_on_false target, push false
            Bytecodes.push_constant,
            # target of the jump in the true branch
            Bytecodes.return_self,
        ],
    )


@pytest.mark.parametrize("or_sel", ["or:", "||"])
def test_inlining_of_or(mgenc, or_sel):
    bytecodes = method_to_bytecodes(
        mgenc, "test = ( true OR_SEL [ #val ] )".replace("OR_SEL", or_sel)
    )

    assert len(bytecodes) == 10
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            BC(Bytecodes.jump_on_true_pop, 7),
            # true branch
            Bytecodes.push_constant_2,  # push the `#val`
            BC(Bytecodes.jump, 4),
            # false branch, jump_on_true target, push true
            Bytecodes.push_constant_0,
            # target of the jump in the true branch
            Bytecodes.return_self,
        ],
    )


def test_field_read_inlining(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(mgenc, "test = ( true and: [ field ] )")

    assert len(bytecodes) == 10
    check(
        bytecodes,
        [
            Bytecodes.push_constant_0,
            BC(Bytecodes.jump_on_false_pop, 7),
            # true branch
            Bytecodes.push_field_0,
            BC(Bytecodes.jump, 4),
            # false branch, jump_on_true target, push true
            Bytecodes.push_constant_2,
            # target of the jump in the true branch
            Bytecodes.return_self,
        ],
    )


def test_inlining_of_to_do(mgenc):
    bytecodes = method_to_bytecodes(mgenc, "test = ( 1 to: 2 do: [:i | i ] )")

    assert len(bytecodes) == 23
    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.push_constant_0,
            Bytecodes.dup_second,  # stack: Top[1, 2, 1]
            Bytecodes.nil_local,
            BC(Bytecodes.jump_if_greater, 17),  # consume only on jump
            Bytecodes.dup,
            BC(
                Bytecodes.pop_local, 0, 0
            ),  # store the i into the local (arg becomes local after inlining)
            BC(
                Bytecodes.push_local, 0, 0
            ),  # push the local on the stack as part of the block's code
            Bytecodes.pop,  # cleanup after block.
            Bytecodes.inc,  # increment top, the iteration counter
            Bytecodes.nil_local,
            BC(
                Bytecodes.jump_backward, 14
            ),  # jump back to the jump_if_greater bytecode
            # jump_if_greater target
            Bytecodes.return_self,
        ],
    )


def test_to_do_block_block_inlined_self(cgenc, mgenc):
    add_field(cgenc, "field")
    bytecodes = method_to_bytecodes(
        mgenc,
        """
        test = (
          | l1 l2 |
          1 to: 2 do: [:a |
            l1 do: [:b |
              b ifTrue: [
                a.
                l2 := l2 + 1 ] ] ]
        )""",
    )

    assert len(bytecodes) == 27
    check(
        bytecodes,
        [
            Bytecodes.push_1,
            Bytecodes.push_constant_0,
            Bytecodes.dup_second,
            Bytecodes.nil_local,
            BC(Bytecodes.jump_if_greater, 21),
            Bytecodes.dup,
            BC(Bytecodes.pop_local, 2, 0),
            BC(Bytecodes.push_local, 0, 0),
            BC(Bytecodes.push_block, 2),
            Bytecodes.send_2,
            Bytecodes.pop,
            Bytecodes.inc,
            Bytecodes.nil_local,
            BC(Bytecodes.jump_backward, 18),
            Bytecodes.return_self,
        ],
    )

    block_method = mgenc._literals[2]  # pylint: disable=protected-access
    block_bcs = block_method.get_bytecodes()
    check(block_bcs, [(6, BC(Bytecodes.push_local, 2, 1)), Bytecodes.pop])
