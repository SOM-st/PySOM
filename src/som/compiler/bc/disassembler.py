from som.compiler.bc.bytecode_generator import compute_offset
from som.vm.current import current_universe
from som.vm.universe import error_print, error_println
from som.interpreter.bc.bytecodes import (
    bytecode_as_str,
    bytecode_length,
    Bytecodes,
    is_one_of,
    JUMP_BYTECODES,
)


def dump(clazz):
    for inv in clazz.get_instance_invokables_for_disassembler():
        # output header and skip if the Invokable is a Primitive
        error_print(str(clazz.get_name()) + ">>" + str(inv.get_signature()) + " = ")

        if inv.is_primitive():
            error_println("<primitive>")
            continue

        # output actual method
        dump_method(inv, "\t")


def dump_method(m, indent):
    error_println("(")

    # output stack information
    error_println(
        "%s<%d locals, %d stack, %d bc_count>"
        % (
            indent,
            m.get_number_of_locals(),
            m.get_maximum_number_of_stack_elements(),
            m.get_number_of_bytecodes(),
        )
    )

    # output bytecodes
    b = 0
    while b < m.get_number_of_bytecodes():
        error_print(indent)
        dump_bytecode(m, b, indent)
        b += bytecode_length(m.get_bytecode(b))

    error_println(indent + ")")


def dump_bytecode(m, b, indent=""):
    # bytecode index
    if b < 10:
        error_print(" ")
    if b < 100:
        error_print(" ")
    error_print(" %d:" % b)

    # mnemonic
    bytecode = m.get_bytecode(b)
    error_print(bytecode_as_str(bytecode) + "  ")

    # parameters (if any)
    if bytecode_length(bytecode) == 1:
        error_println()
        return

    if bytecode == Bytecodes.push_local or bytecode == Bytecodes.pop_local:
        error_println(
            "local: "
            + str(m.get_bytecode(b + 1))
            + ", context: "
            + str(m.get_bytecode(b + 2))
        )
    elif bytecode == Bytecodes.push_argument or bytecode == Bytecodes.pop_argument:
        error_println(
            "argument: "
            + str(m.get_bytecode(b + 1))
            + ", context "
            + str(m.get_bytecode(b + 2))
        )
    elif (
        bytecode == Bytecodes.push_frame
        or bytecode == Bytecodes.pop_frame
        or bytecode == Bytecodes.nil_inner
        or bytecode == Bytecodes.nil_frame
        or bytecode == Bytecodes.nil_local
    ):
        error_println("idx: " + str(m.get_bytecode(b + 1)))
    elif bytecode == Bytecodes.push_inner or bytecode == Bytecodes.pop_inner:
        error_println(
            "idx: "
            + str(m.get_bytecode(b + 1))
            + ", context: "
            + str(m.get_bytecode(b + 2))
        )
    elif (
        bytecode == Bytecodes.push_frame_0
        or bytecode == Bytecodes.push_frame_1
        or bytecode == Bytecodes.push_frame_2
        or bytecode == Bytecodes.pop_frame_0
        or bytecode == Bytecodes.pop_frame_1
        or bytecode == Bytecodes.pop_frame_2
        or bytecode == Bytecodes.push_inner_0
        or bytecode == Bytecodes.push_inner_1
        or bytecode == Bytecodes.push_inner_2
        or bytecode == Bytecodes.pop_inner_0
        or bytecode == Bytecodes.pop_inner_1
        or bytecode == Bytecodes.pop_inner_2
    ):
        # don't need any other arguments
        error_println("")
    elif (
        bytecode == Bytecodes.push_field
        or bytecode == Bytecodes.pop_field
        or bytecode == Bytecodes.inc_field_push
        or bytecode == Bytecodes.inc_field
    ):
        if m.get_holder():
            field_name = str(
                m.get_holder().get_instance_field_name(m.get_bytecode(b + 1))
            )
        else:
            field_name = "Holder Not Set"
        error_println(
            "(index: "
            + str(m.get_bytecode(b + 1))
            + ", context "
            + str(m.get_bytecode(b + 2))
            + ") field: "
            + field_name
        )
    elif bytecode == Bytecodes.push_block:
        error_print("block: (index: " + str(m.get_bytecode(b + 1)) + ") ")
        dump_method(m.get_constant(b), indent + "\t")
    elif bytecode == Bytecodes.push_constant:
        constant = m.get_constant(b)
        try:
            constant_class = constant.get_class(current_universe)
            if constant_class:
                class_name = str(constant_class.get_name())
            else:
                class_name = "not yet supported"
        except:  # pylint: disable=bare-except
            class_name = "not yet supported"

        error_println(
            "(index: "
            + str(m.get_bytecode(b + 1))
            + ") value: ("
            + str(constant)
            + " class: "
            + class_name
            + ") "
        )
    elif bytecode == Bytecodes.push_global:
        error_println(
            "(index: "
            + str(m.get_bytecode(b + 1))
            + ") value: "
            + str(m.get_constant(b))
        )
    elif bytecode in (
        Bytecodes.send_1,
        Bytecodes.send_2,
        Bytecodes.send_3,
        Bytecodes.send_n,
        Bytecodes.super_send,
        Bytecodes.q_super_send_1,
        Bytecodes.q_super_send_2,
        Bytecodes.q_super_send_3,
        Bytecodes.q_super_send_n,
    ):
        error_println(
            "(index: "
            + str(m.get_bytecode(b + 1))
            + ") signature: "
            + str(m.get_constant(b))
        )
    elif bytecode == Bytecodes.push_inner or bytecode == Bytecodes.pop_inner:
        error_println(
            "inner idx: "
            + str(m.get_bytecode(b + 1))
            + ", context "
            + str(m.get_bytecode(b + 2))
        )
    elif bytecode == Bytecodes.push_frame or bytecode == Bytecodes.pop_frame:
        error_println(
            "frame idx: "
            + str(m.get_bytecode(b + 1))
            + ", context "
            + str(m.get_bytecode(b + 2))
        )
    elif bytecode == Bytecodes.return_non_local:
        error_println("context: " + str(m.get_bytecode(b + 1)))
    elif is_one_of(bytecode, JUMP_BYTECODES):
        offset = compute_offset(m.get_bytecode(b + 1), m.get_bytecode(b + 2))
        if bytecode == Bytecodes.jump_backward or bytecode == Bytecodes.jump2_backward:
            target = b - offset
        else:
            target = b + offset

        error_println(
            "(jump offset: " + str(offset) + " -> jump target: " + str(target) + ")"
        )
    else:
        error_println("<incorrect bytecode>")
