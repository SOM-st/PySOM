from som.interpreter.ast.frame import (
    read_frame,
    write_frame,
    write_inner,
    read_inner,
    FRAME_AND_INNER_RCVR_IDX,
    get_inner_as_context,
)
from som.interpreter.ast.nodes.dispatch import (
    CachedDispatchNode,
    INLINE_CACHE_SIZE,
    GenericDispatchNode,
)
from som.interpreter.bc.bytecodes import bytecode_length, Bytecodes, bytecode_as_str
from som.interpreter.bc.frame import (
    get_block_at,
    get_self_dynamically,
)
from som.interpreter.control_flow import ReturnException
from som.interpreter.send import (
    lookup_and_send_2,
    lookup_and_send_3,
)
from som.vm.globals import nilObject, trueObject, falseObject
from som.vmobjects.array import Array
from som.vmobjects.block_bc import BcBlock
from som.vmobjects.integer import int_0, int_1, Integer
from som.vmobjects.double import Double


from rlib import jit
from rlib.jit import promote, elidable_promote, we_are_jitted


def _do_super_send(bytecode_index, method, stack, stack_ptr):
    signature = method.get_constant(bytecode_index)

    receiver_class = method.get_holder().get_super_class()
    invokable = receiver_class.lookup_invokable(signature)

    num_args = invokable.get_number_of_signature_arguments()
    receiver = stack[stack_ptr - (num_args - 1)]

    if invokable:
        method.set_inline_cache(
            bytecode_index, CachedDispatchNode(None, invokable, None)
        )

        if num_args == 1:
            bc = Bytecodes.q_super_send_1
        elif num_args == 2:
            bc = Bytecodes.q_super_send_2
        elif num_args == 3:
            bc = Bytecodes.q_super_send_3
        else:
            bc = Bytecodes.q_super_send_n
        method.set_bytecode(bytecode_index, bc)
        stack_ptr = _invoke_invokable_slow_path(
            invokable, num_args, receiver, stack, stack_ptr
        )
    else:
        stack_ptr = send_does_not_understand(
            receiver, invokable.get_signature(), stack, stack_ptr
        )
    return stack_ptr


@jit.unroll_safe
def _do_return_non_local(result, frame, ctx_level):
    # Compute the context for the non-local return
    block = get_block_at(frame, ctx_level)

    # Make sure the block context is still on the stack
    if not block.is_outer_on_stack():
        # Try to recover by sending 'escapedBlock:' to the self object.
        # That is the most outer self object, not the blockSelf.
        self_block = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
        outer_self = get_self_dynamically(frame)
        return lookup_and_send_2(outer_self, self_block, "escapedBlock:")

    raise ReturnException(result, block.get_on_stack_marker())


def _invoke_invokable_slow_path(invokable, num_args, receiver, stack, stack_ptr):
    if num_args == 1:
        stack[stack_ptr] = invokable.invoke_1(receiver)

    elif num_args == 2:
        arg = stack[stack_ptr]
        if we_are_jitted():
            stack[stack_ptr] = None
        stack_ptr -= 1
        stack[stack_ptr] = invokable.invoke_2(receiver, arg)

    elif num_args == 3:
        arg2 = stack[stack_ptr]
        arg1 = stack[stack_ptr - 1]

        if we_are_jitted():
            stack[stack_ptr] = None
            stack[stack_ptr - 1] = None

        stack_ptr -= 2

        stack[stack_ptr] = invokable.invoke_3(receiver, arg1, arg2)

    else:
        stack_ptr = invokable.invoke_n(stack, stack_ptr)
    return stack_ptr


@jit.unroll_safe
def interpret(method, frame, max_stack_size):
    from som.vm.current import current_universe

    current_bc_idx = 0

    stack_ptr = -1
    stack = [None] * max_stack_size

    while True:
        jitdriver.jit_merge_point(
            current_bc_idx=current_bc_idx,
            stack_ptr=stack_ptr,
            method=method,
            frame=frame,
            stack=stack,
        )

        bytecode = method.get_bytecode(current_bc_idx)

        # Get the length of the current bytecode
        bc_length = bytecode_length(bytecode)

        # Compute the next bytecode index
        next_bc_idx = current_bc_idx + bc_length

        promote(stack_ptr)

        # Handle the current bytecode
        if bytecode == Bytecodes.halt:
            return stack[stack_ptr]

        if bytecode == Bytecodes.dup:
            val = stack[stack_ptr]
            stack_ptr += 1
            stack[stack_ptr] = val

        elif bytecode == Bytecodes.dup_second:
            val = stack[stack_ptr - 1]
            stack_ptr += 1
            stack[stack_ptr] = val

        elif bytecode == Bytecodes.push_frame:
            stack_ptr += 1
            stack[stack_ptr] = read_frame(
                frame, method.get_bytecode(current_bc_idx + 1)
            )

        elif bytecode == Bytecodes.push_frame_0:
            stack_ptr += 1
            stack[stack_ptr] = read_frame(frame, FRAME_AND_INNER_RCVR_IDX + 0)

        elif bytecode == Bytecodes.push_frame_1:
            stack_ptr += 1
            stack[stack_ptr] = read_frame(frame, FRAME_AND_INNER_RCVR_IDX + 1)

        elif bytecode == Bytecodes.push_frame_2:
            stack_ptr += 1
            stack[stack_ptr] = read_frame(frame, FRAME_AND_INNER_RCVR_IDX + 2)

        elif bytecode == Bytecodes.push_inner:
            idx = method.get_bytecode(current_bc_idx + 1)
            ctx_level = method.get_bytecode(current_bc_idx + 2)

            stack_ptr += 1
            if ctx_level == 0:
                stack[stack_ptr] = read_inner(frame, idx)
            else:
                block = get_block_at(frame, ctx_level)
                stack[stack_ptr] = block.get_from_outer(idx)

        elif bytecode == Bytecodes.push_inner_0:
            stack_ptr += 1
            stack[stack_ptr] = read_inner(frame, FRAME_AND_INNER_RCVR_IDX + 0)

        elif bytecode == Bytecodes.push_inner_1:
            stack_ptr += 1
            stack[stack_ptr] = read_inner(frame, FRAME_AND_INNER_RCVR_IDX + 1)

        elif bytecode == Bytecodes.push_inner_2:
            stack_ptr += 1
            stack[stack_ptr] = read_inner(frame, FRAME_AND_INNER_RCVR_IDX + 2)

        elif bytecode == Bytecodes.push_field:
            field_idx = method.get_bytecode(current_bc_idx + 1)
            ctx_level = method.get_bytecode(current_bc_idx + 2)
            self_obj = get_self(frame, ctx_level)
            stack_ptr += 1
            stack[stack_ptr] = self_obj.get_field(field_idx)

        elif bytecode == Bytecodes.push_field_0:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
            stack_ptr += 1
            stack[stack_ptr] = self_obj.get_field(0)

        elif bytecode == Bytecodes.push_field_1:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
            stack_ptr += 1
            stack[stack_ptr] = self_obj.get_field(1)

        elif bytecode == Bytecodes.push_block:
            block_method = method.get_constant(current_bc_idx)
            stack_ptr += 1
            stack[stack_ptr] = BcBlock(block_method, get_inner_as_context(frame))

        elif bytecode == Bytecodes.push_block_no_ctx:
            block_method = method.get_constant(current_bc_idx)
            stack_ptr += 1
            stack[stack_ptr] = BcBlock(block_method, None)

        elif bytecode == Bytecodes.push_constant:
            stack_ptr += 1
            stack[stack_ptr] = method.get_constant(current_bc_idx)

        elif bytecode == Bytecodes.push_constant_0:
            stack_ptr += 1
            stack[stack_ptr] = method._literals[0]  # pylint: disable=protected-access

        elif bytecode == Bytecodes.push_constant_1:
            stack_ptr += 1
            stack[stack_ptr] = method._literals[1]  # pylint: disable=protected-access

        elif bytecode == Bytecodes.push_constant_2:
            stack_ptr += 1
            stack[stack_ptr] = method._literals[2]  # pylint: disable=protected-access

        elif bytecode == Bytecodes.push_0:
            stack_ptr += 1
            stack[stack_ptr] = int_0

        elif bytecode == Bytecodes.push_1:
            stack_ptr += 1
            stack[stack_ptr] = int_1

        elif bytecode == Bytecodes.push_nil:
            stack_ptr += 1
            stack[stack_ptr] = nilObject

        elif bytecode == Bytecodes.push_global:
            global_name = method.get_constant(current_bc_idx)
            glob = current_universe.get_global(global_name)

            stack_ptr += 1
            if glob:
                stack[stack_ptr] = glob
            else:
                stack[stack_ptr] = lookup_and_send_2(
                    get_self_dynamically(frame), global_name, "unknownGlobal:"
                )

        elif bytecode == Bytecodes.pop:
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

        elif bytecode == Bytecodes.pop_frame:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1
            write_frame(frame, method.get_bytecode(current_bc_idx + 1), value)

        elif bytecode == Bytecodes.pop_frame_0:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1
            write_frame(frame, FRAME_AND_INNER_RCVR_IDX + 0, value)

        elif bytecode == Bytecodes.pop_frame_1:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1
            write_frame(frame, FRAME_AND_INNER_RCVR_IDX + 1, value)

        elif bytecode == Bytecodes.pop_frame_2:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1
            write_frame(frame, FRAME_AND_INNER_RCVR_IDX + 2, value)

        elif bytecode == Bytecodes.pop_inner:
            idx = method.get_bytecode(current_bc_idx + 1)
            ctx_level = method.get_bytecode(current_bc_idx + 2)
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            if ctx_level == 0:
                write_inner(frame, idx, value)
            else:
                block = get_block_at(frame, ctx_level)
                block.set_outer(idx, value)

        elif bytecode == Bytecodes.pop_inner_0:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            write_inner(frame, FRAME_AND_INNER_RCVR_IDX + 0, value)

        elif bytecode == Bytecodes.pop_inner_1:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            write_inner(frame, FRAME_AND_INNER_RCVR_IDX + 1, value)

        elif bytecode == Bytecodes.pop_inner_2:
            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            write_inner(frame, FRAME_AND_INNER_RCVR_IDX + 2, value)

        elif bytecode == Bytecodes.nil_frame:
            if we_are_jitted():
                idx = method.get_bytecode(current_bc_idx + 1)
                write_frame(frame, idx, nilObject)

        elif bytecode == Bytecodes.nil_inner:
            if we_are_jitted():
                idx = method.get_bytecode(current_bc_idx + 1)
                write_inner(frame, idx, nilObject)

        elif bytecode == Bytecodes.pop_field:
            field_idx = method.get_bytecode(current_bc_idx + 1)
            ctx_level = method.get_bytecode(current_bc_idx + 2)
            self_obj = get_self(frame, ctx_level)

            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            self_obj.set_field(field_idx, value)

        elif bytecode == Bytecodes.pop_field_0:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)

            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            self_obj.set_field(0, value)

        elif bytecode == Bytecodes.pop_field_1:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)

            value = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

            self_obj.set_field(1, value)

        elif bytecode == Bytecodes.send_1:
            receiver = stack[stack_ptr]

            layout = receiver.get_object_layout(current_universe)
            dispatch_node = _lookup(layout, method, current_bc_idx, current_universe)

            if not layout.is_latest:
                _update_object_and_invalidate_old_caches(
                    receiver, method, current_bc_idx, current_universe
                )

            stack[stack_ptr] = dispatch_node.dispatch_1(receiver)

        elif bytecode == Bytecodes.send_2:
            receiver = stack[stack_ptr - 1]

            layout = receiver.get_object_layout(current_universe)
            dispatch_node = _lookup(layout, method, current_bc_idx, current_universe)

            if not layout.is_latest:
                _update_object_and_invalidate_old_caches(
                    receiver, method, current_bc_idx, current_universe
                )

            arg = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None

            stack_ptr -= 1
            stack[stack_ptr] = dispatch_node.dispatch_2(receiver, arg)

        elif bytecode == Bytecodes.send_3:
            receiver = stack[stack_ptr - 2]

            layout = receiver.get_object_layout(current_universe)
            dispatch_node = _lookup(layout, method, current_bc_idx, current_universe)

            if not layout.is_latest:
                _update_object_and_invalidate_old_caches(
                    receiver, method, current_bc_idx, current_universe
                )

            arg2 = stack[stack_ptr]
            arg1 = stack[stack_ptr - 1]
            if we_are_jitted():
                stack[stack_ptr] = None
                stack[stack_ptr - 1] = None

            stack_ptr -= 2
            stack[stack_ptr] = dispatch_node.dispatch_3(receiver, arg1, arg2)

        elif bytecode == Bytecodes.send_n:
            signature = method.get_constant(current_bc_idx)
            receiver = stack[
                stack_ptr - (signature.get_number_of_signature_arguments() - 1)
            ]

            layout = receiver.get_object_layout(current_universe)
            dispatch_node = _lookup(layout, method, current_bc_idx, current_universe)

            if not layout.is_latest:
                _update_object_and_invalidate_old_caches(
                    receiver, method, current_bc_idx, current_universe
                )

            stack_ptr = dispatch_node.dispatch_n_bc(stack, stack_ptr, receiver)

        elif bytecode == Bytecodes.super_send:
            stack_ptr = _do_super_send(current_bc_idx, method, stack, stack_ptr)

        elif bytecode == Bytecodes.return_local:
            return stack[stack_ptr]

        elif bytecode == Bytecodes.return_non_local:
            val = stack[stack_ptr]
            return _do_return_non_local(
                val, frame, method.get_bytecode(current_bc_idx + 1)
            )

        elif bytecode == Bytecodes.return_self:
            return read_frame(frame, FRAME_AND_INNER_RCVR_IDX)

        elif bytecode == Bytecodes.return_field_0:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
            return self_obj.get_field(0)

        elif bytecode == Bytecodes.return_field_1:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
            return self_obj.get_field(1)

        elif bytecode == Bytecodes.return_field_2:
            self_obj = read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
            return self_obj.get_field(2)

        elif bytecode == Bytecodes.inc:
            val = stack[stack_ptr]
            from som.vmobjects.biginteger import BigInteger

            if isinstance(val, Integer):
                result = val.prim_inc()
            elif isinstance(val, Double):
                result = val.prim_inc()
            elif isinstance(val, BigInteger):
                result = val.prim_inc()
            else:
                return _not_yet_implemented()
            stack[stack_ptr] = result

        elif bytecode == Bytecodes.dec:
            val = stack[stack_ptr]
            from som.vmobjects.biginteger import BigInteger

            if isinstance(val, Integer):
                result = val.prim_dec()
            elif isinstance(val, Double):
                result = val.prim_dec()
            elif isinstance(val, BigInteger):
                result = val.prim_dec()
            else:
                return _not_yet_implemented()
            stack[stack_ptr] = result

        elif bytecode == Bytecodes.inc_field:
            field_idx = method.get_bytecode(current_bc_idx + 1)
            ctx_level = method.get_bytecode(current_bc_idx + 2)
            self_obj = get_self(frame, ctx_level)

            self_obj.inc_field(field_idx)

        elif bytecode == Bytecodes.inc_field_push:
            field_idx = method.get_bytecode(current_bc_idx + 1)
            ctx_level = method.get_bytecode(current_bc_idx + 2)
            self_obj = get_self(frame, ctx_level)

            stack_ptr += 1
            stack[stack_ptr] = self_obj.inc_field(field_idx)

        elif bytecode == Bytecodes.jump:
            next_bc_idx = current_bc_idx + method.get_bytecode(current_bc_idx + 1)

        elif bytecode == Bytecodes.jump_on_true_top_nil:
            val = stack[stack_ptr]
            if val is trueObject:
                next_bc_idx = current_bc_idx + method.get_bytecode(current_bc_idx + 1)
                stack[stack_ptr] = nilObject
            else:
                if we_are_jitted():
                    stack[stack_ptr] = None
                stack_ptr -= 1

        elif bytecode == Bytecodes.jump_on_false_top_nil:
            val = stack[stack_ptr]
            if val is falseObject:
                next_bc_idx = current_bc_idx + method.get_bytecode(current_bc_idx + 1)
                stack[stack_ptr] = nilObject
            else:
                if we_are_jitted():
                    stack[stack_ptr] = None
                stack_ptr -= 1

        elif bytecode == Bytecodes.jump_on_true_pop:
            val = stack[stack_ptr]
            if val is trueObject:
                next_bc_idx = current_bc_idx + method.get_bytecode(current_bc_idx + 1)
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

        elif bytecode == Bytecodes.jump_on_false_pop:
            val = stack[stack_ptr]
            if val is falseObject:
                next_bc_idx = current_bc_idx + method.get_bytecode(current_bc_idx + 1)
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

        elif bytecode == Bytecodes.jump_if_greater:
            top = stack[stack_ptr]
            top_2 = stack[stack_ptr - 1]
            if (
                isinstance(top, Integer)
                and isinstance(top_2, Integer)
                and top.get_embedded_integer() > top_2.get_embedded_integer()
            ) or (
                isinstance(top, Double)
                and isinstance(top_2, Double)
                and top.get_embedded_double() > top_2.get_embedded_double()
            ):
                stack[stack_ptr] = None
                stack[stack_ptr - 1] = None
                stack_ptr -= 2
                next_bc_idx = current_bc_idx + method.get_bytecode(current_bc_idx + 1)

        elif bytecode == Bytecodes.jump_backward:
            next_bc_idx = current_bc_idx - method.get_bytecode(current_bc_idx + 1)
            jitdriver.can_enter_jit(
                current_bc_idx=next_bc_idx,
                stack_ptr=stack_ptr,
                method=method,
                frame=frame,
                stack=stack,
            )

        elif bytecode == Bytecodes.jump2:
            next_bc_idx = (
                current_bc_idx
                + method.get_bytecode(current_bc_idx + 1)
                + (method.get_bytecode(current_bc_idx + 2) << 8)
            )

        elif bytecode == Bytecodes.jump2_on_true_top_nil:
            val = stack[stack_ptr]
            if val is trueObject:
                next_bc_idx = (
                    current_bc_idx
                    + method.get_bytecode(current_bc_idx + 1)
                    + (method.get_bytecode(current_bc_idx + 2) << 8)
                )
                stack[stack_ptr] = nilObject
            else:
                if we_are_jitted():
                    stack[stack_ptr] = None
                stack_ptr -= 1

        elif bytecode == Bytecodes.jump2_on_false_top_nil:
            val = stack[stack_ptr]
            if val is falseObject:
                next_bc_idx = (
                    current_bc_idx
                    + method.get_bytecode(current_bc_idx + 1)
                    + (method.get_bytecode(current_bc_idx + 2) << 8)
                )
                stack[stack_ptr] = nilObject
            else:
                if we_are_jitted():
                    stack[stack_ptr] = None
                stack_ptr -= 1

        elif bytecode == Bytecodes.jump2_on_true_pop:
            val = stack[stack_ptr]
            if val is trueObject:
                next_bc_idx = (
                    current_bc_idx
                    + method.get_bytecode(current_bc_idx + 1)
                    + (method.get_bytecode(current_bc_idx + 2) << 8)
                )
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

        elif bytecode == Bytecodes.jump2_on_false_pop:
            val = stack[stack_ptr]
            if val is falseObject:
                next_bc_idx = (
                    current_bc_idx
                    + method.get_bytecode(current_bc_idx + 1)
                    + (method.get_bytecode(current_bc_idx + 2) << 8)
                )
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1

        elif bytecode == Bytecodes.jump2_if_greater:
            top = stack[stack_ptr]
            top_2 = stack[stack_ptr - 1]
            if top.get_embedded_integer() > top_2.get_embedded_integer():
                stack[stack_ptr] = None
                stack[stack_ptr - 1] = None
                stack_ptr -= 2
                next_bc_idx = (
                    current_bc_idx
                    + method.get_bytecode(current_bc_idx + 1)
                    + (method.get_bytecode(current_bc_idx + 2) << 8)
                )

        elif bytecode == Bytecodes.jump2_backward:
            next_bc_idx = current_bc_idx - (
                method.get_bytecode(current_bc_idx + 1)
                + (method.get_bytecode(current_bc_idx + 2) << 8)
            )
            jitdriver.can_enter_jit(
                current_bc_idx=next_bc_idx,
                stack_ptr=stack_ptr,
                method=method,
                frame=frame,
                stack=stack,
            )

        elif bytecode == Bytecodes.q_super_send_1:
            dispatch_node = method.get_inline_cache(current_bc_idx)
            stack[stack_ptr] = dispatch_node.dispatch_1(stack[stack_ptr])

        elif bytecode == Bytecodes.q_super_send_2:
            dispatch_node = method.get_inline_cache(current_bc_idx)
            arg = stack[stack_ptr]
            if we_are_jitted():
                stack[stack_ptr] = None
            stack_ptr -= 1
            stack[stack_ptr] = dispatch_node.dispatch_2(stack[stack_ptr], arg)

        elif bytecode == Bytecodes.q_super_send_3:
            dispatch_node = method.get_inline_cache(current_bc_idx)
            arg2 = stack[stack_ptr]
            arg1 = stack[stack_ptr - 1]
            if we_are_jitted():
                stack[stack_ptr] = None
                stack[stack_ptr - 1] = None
            stack_ptr -= 2
            stack[stack_ptr] = dispatch_node.dispatch_3(stack[stack_ptr], arg1, arg2)

        elif bytecode == Bytecodes.q_super_send_n:
            dispatch_node = method.get_inline_cache(current_bc_idx)
            stack_ptr = dispatch_node.dispatch_n_bc(stack, stack_ptr, None)

        elif bytecode == Bytecodes.push_local:
            method.patch_variable_access(current_bc_idx)
            # retry bytecode after patching
            next_bc_idx = current_bc_idx
        elif bytecode == Bytecodes.push_argument:
            method.patch_variable_access(current_bc_idx)
            # retry bytecode after patching
            next_bc_idx = current_bc_idx
        elif bytecode == Bytecodes.pop_local:
            method.patch_variable_access(current_bc_idx)
            # retry bytecode after patching
            next_bc_idx = current_bc_idx
        elif bytecode == Bytecodes.pop_argument:
            method.patch_variable_access(current_bc_idx)
            # retry bytecode after patching
            next_bc_idx = current_bc_idx
        elif bytecode == Bytecodes.nil_local:
            method.patch_variable_access(current_bc_idx)
            # retry bytecode after patching
            next_bc_idx = current_bc_idx
        else:
            _unknown_bytecode(bytecode, current_bc_idx, method)

        current_bc_idx = next_bc_idx


def _not_yet_implemented():
    raise Exception("Not yet implemented")


def _unknown_bytecode(bytecode, bytecode_idx, method):
    from som.compiler.bc.disassembler import dump_method

    dump_method(method, "")
    raise Exception(
        "Unknown bytecode: "
        + str(bytecode)
        + " "
        + bytecode_as_str(bytecode)
        + " at bci: "
        + str(bytecode_idx)
    )


def get_self(frame, ctx_level):
    # Get the self object from the interpreter
    if ctx_level == 0:
        return read_frame(frame, FRAME_AND_INNER_RCVR_IDX)
    return get_block_at(frame, ctx_level).get_from_outer(FRAME_AND_INNER_RCVR_IDX)


@elidable_promote("all")
def _lookup(layout, method, bytecode_index, universe):
    cache = first = method.get_inline_cache(bytecode_index)
    while cache is not None:
        if cache.expected_layout is layout:
            return cache
        cache = cache.next_entry

    # this is the generic dispatch node
    if first and first.expected_layout is None:
        return first

    # get size of cache
    cache_size = 0
    while cache is not None:
        cache = cache.next_entry
        cache_size += 1

    # read the selector only now when we will actually need it
    selector = method.get_constant(bytecode_index)

    if INLINE_CACHE_SIZE >= cache_size:
        invoke = layout.lookup_invokable(selector)
        if invoke is not None:
            new_dispatch_node = CachedDispatchNode(
                rcvr_class=layout, method=invoke, next_entry=first
            )
            method.set_inline_cache(bytecode_index, new_dispatch_node)
            return new_dispatch_node

    generic = GenericDispatchNode(selector, universe)
    method.set_inline_cache(bytecode_index, generic)
    return generic


def _update_object_and_invalidate_old_caches(obj, method, bytecode_index, universe):
    obj.update_layout_to_match_class()
    obj.get_object_layout(universe)
    method.drop_old_inline_cache_entries(bytecode_index)


def send_does_not_understand(receiver, selector, stack, stack_ptr):
    # ignore self
    number_of_arguments = selector.get_number_of_signature_arguments() - 1
    arguments_array = Array.from_size(number_of_arguments)

    # Remove all arguments and put them in the freshly allocated array
    i = number_of_arguments - 1
    while i >= 0:
        value = stack[stack_ptr]
        if we_are_jitted():
            stack[stack_ptr] = None
        stack_ptr -= 1

        arguments_array.set_indexable_field(i, value)
        i -= 1

    stack[stack_ptr] = lookup_and_send_3(
        receiver, selector, arguments_array, "doesNotUnderstand:arguments:"
    )

    return stack_ptr


def get_printable_location(bytecode_index, method):
    from som.vmobjects.method_bc import BcAbstractMethod

    assert isinstance(method, BcAbstractMethod)
    bc = method.get_bytecode(bytecode_index)
    return "%s @ %d in %s" % (
        bytecode_as_str(bc),
        bytecode_index,
        method.merge_point_string(),
    )


jitdriver = jit.JitDriver(
    name="Interpreter",
    greens=["current_bc_idx", "method"],
    reds=["stack_ptr", "frame", "stack"],
    # virtualizables=['frame'],
    get_printable_location=get_printable_location,
    # the next line is a workaround around a likely bug in RPython
    # for some reason, the inlining heuristics default to "never inline" when
    # two different jit drivers are involved (in our case, the primitive
    # driver, and this one).
    # the next line says that calls involving this jitdriver should always be
    # inlined once (which means that things like Integer>>< will be inlined
    # into a while loop again, when enabling this drivers).
    should_unroll_one_iteration=lambda current_bc_idx, method: True,
)


def jitpolicy(_driver):
    from rpython.jit.codewriter.policy import JitPolicy  # pylint: disable=import-error

    return JitPolicy()
