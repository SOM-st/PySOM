from rlib import jit


class Bytecodes(object):
    # Bytecodes used by the Simple Object Machine (SOM)
    halt = 0
    dup = halt + 1
    dup_second = dup + 1

    push_frame = dup_second + 1
    push_frame_0 = push_frame + 1
    push_frame_1 = push_frame_0 + 1
    push_frame_2 = push_frame_1 + 1

    push_inner = push_frame_2 + 1
    push_inner_0 = push_inner + 1
    push_inner_1 = push_inner_0 + 1
    push_inner_2 = push_inner_1 + 1

    push_field = push_inner_2 + 1
    push_field_0 = push_field + 1
    push_field_1 = push_field_0 + 1

    push_block = push_field_1 + 1
    push_block_no_ctx = push_block + 1

    push_constant = push_block_no_ctx + 1
    push_constant_0 = push_constant + 1
    push_constant_1 = push_constant_0 + 1
    push_constant_2 = push_constant_1 + 1

    push_0 = push_constant_2 + 1
    push_1 = push_0 + 1
    push_nil = push_1 + 1

    push_global = push_nil + 1

    pop = push_global + 1

    pop_frame = pop + 1
    pop_frame_0 = pop_frame + 1
    pop_frame_1 = pop_frame_0 + 1
    pop_frame_2 = pop_frame_1 + 1

    pop_inner = pop_frame_2 + 1
    pop_inner_0 = pop_inner + 1
    pop_inner_1 = pop_inner_0 + 1
    pop_inner_2 = pop_inner_1 + 1

    pop_field = pop_inner_2 + 1
    pop_field_0 = pop_field + 1
    pop_field_1 = pop_field_0 + 1

    nil_frame = pop_field_1 + 1
    nil_inner = nil_frame + 1

    send_1 = nil_inner + 1
    send_2 = send_1 + 1
    send_3 = send_2 + 1
    send_n = send_3 + 1

    super_send = send_n + 1

    return_local = super_send + 1
    return_non_local = return_local + 1
    return_self = return_non_local + 1

    return_field_0 = return_self + 1
    return_field_1 = return_field_0 + 1
    return_field_2 = return_field_1 + 1

    inc = return_field_2 + 1
    dec = inc + 1

    inc_field = dec + 1
    inc_field_push = inc_field + 1

    jump = inc_field_push + 1
    jump_on_true_top_nil = jump + 1
    jump_on_false_top_nil = jump_on_true_top_nil + 1
    jump_on_true_pop = jump_on_false_top_nil + 1
    jump_on_false_pop = jump_on_true_pop + 1
    jump_if_greater = jump_on_false_pop + 1
    jump_backward = jump_if_greater + 1
    jump2 = jump_backward + 1
    jump2_on_true_top_nil = jump2 + 1
    jump2_on_false_top_nil = jump2_on_true_top_nil + 1
    jump2_on_true_pop = jump2_on_false_top_nil + 1
    jump2_on_false_pop = jump2_on_true_pop + 1
    jump2_if_greater = jump2_on_false_pop + 1
    jump2_backward = jump2_if_greater + 1

    q_super_send_1 = jump2_backward + 1
    q_super_send_2 = q_super_send_1 + 1
    q_super_send_3 = q_super_send_2 + 1
    q_super_send_n = q_super_send_3 + 1

    push_local = q_super_send_n + 1
    push_argument = push_local + 1
    pop_local = push_argument + 1
    pop_argument = pop_local + 1
    nil_local = pop_argument + 1

    invalid = nil_local + 1


def is_one_of(bytecode, candidates):
    for c in candidates:
        if c == bytecode:
            return True
    return False


_NUM_BYTECODES = Bytecodes.pop_argument + 1

POP_X_BYTECODES = [
    Bytecodes.pop_local,
    Bytecodes.pop_argument,
    Bytecodes.pop_field,
    Bytecodes.pop_field_0,
    Bytecodes.pop_field_1,
]

PUSH_BLOCK_BYTECODES = [Bytecodes.push_block, Bytecodes.push_block_no_ctx]

PUSH_CONST_BYTECODES = [
    Bytecodes.push_constant,
    Bytecodes.push_constant_0,
    Bytecodes.push_constant_1,
    Bytecodes.push_constant_2,
    Bytecodes.push_0,
    Bytecodes.push_1,
    Bytecodes.push_nil,
]

PUSH_FIELD_BYTECODES = [
    Bytecodes.push_field,
    Bytecodes.push_field_0,
    Bytecodes.push_field_1,
]

POP_FIELD_BYTECODES = [
    Bytecodes.pop_field,
    Bytecodes.pop_field_0,
    Bytecodes.pop_field_1,
]

RETURN_FIELD_BYTECODES = [
    Bytecodes.return_field_0,
    Bytecodes.return_field_1,
    Bytecodes.return_field_2,
]

JUMP_BYTECODES = [
    Bytecodes.jump,
    Bytecodes.jump_on_true_top_nil,
    Bytecodes.jump_on_true_pop,
    Bytecodes.jump_on_false_pop,
    Bytecodes.jump_on_false_top_nil,
    Bytecodes.jump_if_greater,
    Bytecodes.jump_backward,
    Bytecodes.jump2,
    Bytecodes.jump2_on_true_top_nil,
    Bytecodes.jump2_on_true_pop,
    Bytecodes.jump2_on_false_pop,
    Bytecodes.jump2_on_false_top_nil,
    Bytecodes.jump2_if_greater,
    Bytecodes.jump2_backward,
]

FIRST_DOUBLE_BYTE_JUMP_BYTECODE = Bytecodes.jump2
NUM_SINGLE_BYTE_JUMP_BYTECODES = int(len(JUMP_BYTECODES) / 2)

RUN_TIME_ONLY_BYTECODES = [
    Bytecodes.push_frame,
    Bytecodes.push_frame_0,
    Bytecodes.push_frame_1,
    Bytecodes.push_frame_2,
    Bytecodes.push_inner,
    Bytecodes.push_inner_1,
    Bytecodes.push_inner_2,
    Bytecodes.pop_frame,
    Bytecodes.pop_frame_1,
    Bytecodes.pop_frame_2,
    Bytecodes.pop_inner,
    Bytecodes.pop_inner_0,
    Bytecodes.pop_inner_1,
    Bytecodes.pop_inner_2,
    Bytecodes.nil_frame,
    Bytecodes.nil_inner,
    Bytecodes.q_super_send_1,
    Bytecodes.q_super_send_2,
    Bytecodes.q_super_send_3,
    Bytecodes.q_super_send_n,
]

NOT_EXPECTED_IN_BLOCK_BYTECODES = [
    Bytecodes.halt,
    Bytecodes.push_field_0,
    Bytecodes.push_field_1,
    Bytecodes.pop_field_0,
    Bytecodes.pop_field_1,
    Bytecodes.return_self,
    Bytecodes.return_field_0,
    Bytecodes.return_field_1,
    Bytecodes.return_field_2,
]

_BYTECODE_LENGTH = [
    1,  # halt
    1,  # dup
    1,  # dup_second
    3,  # push_frame
    3,  # push_frame_0
    3,  # push_frame_1
    3,  # push_frame_2
    3,  # push_inner
    3,  # push_inner_0
    3,  # push_inner_1
    3,  # push_inner_2
    3,  # push_field
    1,  # push_field_0
    1,  # push_field_1
    2,  # push_block
    2,  # push_block_no_ctx
    2,  # push_constant
    1,  # push_constant_0
    1,  # push_constant_1
    1,  # push_constant_2
    1,  # push_0
    1,  # push_1
    1,  # push_nil
    2,  # push_global
    1,  # pop
    3,  # pop_frame
    3,  # pop_frame_0
    3,  # pop_frame_1
    3,  # pop_frame_2
    3,  # pop_inner
    3,  # pop_inner_0
    3,  # pop_inner_1
    3,  # pop_inner_2
    3,  # pop_field
    1,  # pop_field_0
    1,  # pop_field_1
    2,  # nil_frame
    2,  # nil_inner
    2,  # send_1
    2,  # send_2
    2,  # send_3
    2,  # send_n
    2,  # super_send
    1,  # return_local
    2,  # return_non_local
    1,  # return_self
    1,  # return_field_0
    1,  # return_field_1
    1,  # return_field_2
    1,  # inc
    1,  # dec
    3,  # inc_field
    3,  # inc_field_push
    3,  # jump
    3,  # jump_on_true_top_nil
    3,  # jump_on_false_top_nil
    3,  # jump_on_true_pop
    3,  # jump_on_false_pop
    3,  # jump_if_greater
    3,  # jump_backward
    3,  # jump2
    3,  # jump2_on_true_top_nil
    3,  # jump2_on_false_top_nil
    3,  # jump2_on_true_pop
    3,  # jump2_on_false_pop
    3,  # jump2_if_greater
    3,  # jump2_backward
    2,  # q_super_send_1
    2,  # q_super_send_2
    2,  # q_super_send_3
    2,  # q_super_send_n
    # rewritten on first use
    3,  # push_local
    3,  # push_argument
    3,  # pop_local
    3,  # pop_argument
    2,  # nil_local
]


@jit.elidable
def bytecode_length(bytecode):
    assert 0 <= bytecode < len(_BYTECODE_LENGTH)
    return _BYTECODE_LENGTH[bytecode]


@jit.elidable
def bytecode_as_str(bytecode):
    assert 0 <= bytecode < len(_BYTECODE_NAMES)
    return _BYTECODE_NAMES[bytecode]


def _sorted_bytecode_names(cls):
    "NOT_RPYTHON"
    """This function is only called a single time, at load time of this module.
       For RPypthon, this means, during translation of the module.
    """
    return [
        key.upper()
        for value, key in sorted(
            [
                (value, key)
                for key, value in cls.__dict__.items()
                if isinstance(value, int) and key[0] != "_"
            ]
        )
    ]


_BYTECODE_NAMES = _sorted_bytecode_names(Bytecodes)
