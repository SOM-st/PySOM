from __future__ import absolute_import

from rlib import jit
from rlib.min_heap_queue import heappush, heappop, HeapEntry
from som.compiler.bc.bytecode_generator import (
    emit1,
    emit3,
    emit_push_constant,
    emit_return_local,
    emit_return_non_local,
    emit_send,
    emit_super_send,
    emit_push_global,
    emit_push_block,
    emit_push_field_with_index,
    emit_pop_field_with_index,
    emit3_with_dummy,
    emit_push_local,
    emit_pop_local,
    emit_nil_local,
    compute_offset,
)
from som.interpreter.ast.frame import (
    get_inner_as_context,
    mark_as_no_longer_on_stack,
    FRAME_AND_INNER_RCVR_IDX,
    create_frame_1,
    create_frame_2,
)
from som.interpreter.bc.bytecodes import (
    Bytecodes,
    bytecode_length,
    RUN_TIME_ONLY_BYTECODES,
    bytecode_as_str,
    NOT_EXPECTED_IN_BLOCK_BYTECODES,
)

from som.interpreter.bc.frame import (
    create_frame,
    stack_pop_old_arguments_and_push_result,
    create_frame_3,
)
from som.interpreter.bc.interpreter import interpret
from som.interpreter.control_flow import ReturnException
from som.vmobjects.abstract_object import AbstractObject
from som.vmobjects.method import AbstractMethod


class BcAbstractMethod(AbstractMethod):
    _immutable_fields_ = [
        "_bytecodes?[*]",
        "_literals[*]",
        "_inline_cache",
        "_number_of_locals",
        "_maximum_number_of_stack_elements",
        "_number_of_arguments",
        "_arg_inner_access[*]",
        "_size_frame",
        "_size_inner",
        "_inlined_loops[*]",
    ]

    def __init__(
        self,
        literals,
        num_locals,
        max_stack_elements,
        num_bytecodes,
        signature,
        arg_inner_access,
        size_frame,
        size_inner,
        lexical_scope,
        inlined_loops,
    ):
        AbstractMethod.__init__(self, signature, lexical_scope)

        # Set the number of bytecodes in this method
        self._bytecodes = ["\x00"] * num_bytecodes
        self._inline_cache = [None] * num_bytecodes

        self._literals = literals

        self._number_of_arguments = signature.get_number_of_signature_arguments()
        self._number_of_locals = num_locals
        self._maximum_number_of_stack_elements = max_stack_elements + 2

        self._arg_inner_access = arg_inner_access
        self._size_frame = size_frame
        self._size_inner = size_inner

        self._inlined_loops = inlined_loops

    def get_number_of_locals(self):
        return self._number_of_locals

    @jit.elidable_promote("all")
    def get_maximum_number_of_stack_elements(self):
        # Compute the maximum number of stack locations (including
        # extra buffer to support doesNotUnderstand) and set the
        # number of indexable fields accordingly
        return self._maximum_number_of_stack_elements

    def set_holder(self, value):
        self._holder = value

        # Make sure all nested invokables have the same holder
        for obj in self._literals:
            assert isinstance(obj, AbstractObject)
            if obj.is_invokable():
                obj.set_holder(value)

    # XXX this means that the JIT doesn't see changes to the constants
    @jit.elidable_promote("all")
    def get_constant(self, bytecode_index):
        # Get the constant associated to a given bytecode index
        return self._literals[self.get_bytecode(bytecode_index + 1)]

    @jit.elidable_promote("all")
    def get_number_of_arguments(self):
        return self._number_of_arguments

    @jit.elidable_promote("all")
    def get_number_of_signature_arguments(self):
        return self._number_of_arguments

    def get_number_of_bytecodes(self):
        # Get the number of bytecodes in this method
        return len(self._bytecodes)

    @jit.elidable_promote("all")
    def get_bytecode(self, index):
        # Get the bytecode at the given index
        assert 0 <= index < len(self._bytecodes)
        return ord(self._bytecodes[index])

    def get_bytecodes(self):
        """For testing purposes only"""
        return [ord(b) for b in self._bytecodes]

    def set_bytecode(self, index, value):
        # Set the bytecode at the given index to the given value
        assert (
            0 <= value <= 255
        ), "Expected bytecode in the range of [0..255], but was: " + str(value)
        self._bytecodes[index] = chr(value)

    @jit.elidable
    def get_inline_cache(self, bytecode_index):
        assert 0 <= bytecode_index < len(self._inline_cache)
        return self._inline_cache[bytecode_index]

    def set_inline_cache(self, bytecode_index, dispatch_node):
        self._inline_cache[bytecode_index] = dispatch_node

    def drop_old_inline_cache_entries(self, bytecode_index):
        # Keep in sync with _AbstractGenericMessageNode._get_cache_size_and_drop_old_entries
        prev = None
        cache = self._inline_cache[bytecode_index]

        while cache is not None:
            if not cache.expected_layout.is_latest:
                # drop old layout from cache
                if prev is None:
                    self._inline_cache[bytecode_index] = cache.next_entry
                else:
                    prev.next_entry = cache.next_entry
            else:
                prev = cache

            cache = cache.next_entry

    def patch_variable_access(self, bytecode_index):
        bc = self.get_bytecode(bytecode_index)
        idx = self.get_bytecode(bytecode_index + 1)
        ctx_level = self.get_bytecode(bytecode_index + 2)

        if bc == Bytecodes.push_argument:
            var = self._lexical_scope.get_argument(idx, ctx_level)
            self.set_bytecode(bytecode_index, var.get_push_bytecode(ctx_level))
        elif bc == Bytecodes.pop_argument:
            var = self._lexical_scope.get_argument(idx, ctx_level)
            self.set_bytecode(bytecode_index, var.get_pop_bytecode(ctx_level))
        elif bc == Bytecodes.push_local:
            var = self._lexical_scope.get_local(idx, ctx_level)
            self.set_bytecode(bytecode_index, var.get_push_bytecode(ctx_level))
        elif bc == Bytecodes.pop_local:
            var = self._lexical_scope.get_local(idx, ctx_level)
            self.set_bytecode(bytecode_index, var.get_pop_bytecode(ctx_level))
        elif bc == Bytecodes.nil_local:
            var = self._lexical_scope.get_local(idx, 0)
            if var.is_accessed_out_of_context():
                bytecode = Bytecodes.nil_inner
            else:
                bytecode = Bytecodes.nil_frame
            self.set_bytecode(bytecode_index, bytecode)
        else:
            raise Exception("Unsupported bytecode?")
        assert (
            FRAME_AND_INNER_RCVR_IDX <= var.access_idx <= 255
        ), "Expected variable access index to be in valid range, but was " + str(
            var.access_idx
        )
        self.set_bytecode(bytecode_index + 1, var.access_idx)


def _interp_with_nlr(method, new_frame, max_stack_size):
    inner = get_inner_as_context(new_frame)

    try:
        result = interpret(method, new_frame, max_stack_size)
        mark_as_no_longer_on_stack(inner)
        return result
    except ReturnException as e:
        mark_as_no_longer_on_stack(inner)
        if e.has_reached_target(inner):
            return e.get_result()
        raise e


class BcMethod(BcAbstractMethod):
    def invoke_1(self, rcvr):
        new_frame = create_frame_1(rcvr, self._size_frame, self._size_inner)
        return interpret(self, new_frame, self._maximum_number_of_stack_elements)

    def invoke_2(self, rcvr, arg1):
        new_frame = create_frame_2(
            rcvr,
            arg1,
            self._arg_inner_access[0],
            self._size_frame,
            self._size_inner,
        )
        return interpret(self, new_frame, self._maximum_number_of_stack_elements)

    def invoke_3(self, rcvr, arg1, arg2):
        new_frame = create_frame_3(
            self._arg_inner_access,
            self._size_frame,
            self._size_inner,
            rcvr,
            arg1,
            arg2,
        )
        return interpret(self, new_frame, self._maximum_number_of_stack_elements)

    def invoke_n(self, stack, stack_ptr):
        new_frame = create_frame(
            self._arg_inner_access,
            self._size_frame,
            self._size_inner,
            stack,
            stack_ptr,
            self._number_of_arguments,
        )

        result = interpret(self, new_frame, self._maximum_number_of_stack_elements)
        return stack_pop_old_arguments_and_push_result(
            stack, stack_ptr, self._number_of_arguments, result
        )

    def merge_scope_into(self, mgenc):
        mgenc.merge_into_scope(self._lexical_scope)

    def inline(self, mgenc, merge_scope=True):
        if merge_scope:
            mgenc.merge_into_scope(self._lexical_scope)
        self._inline_into(mgenc)

    def _create_back_jump_heap(self):
        heap = []
        if self._inlined_loops:
            for loop in self._inlined_loops:
                heappush(heap, loop)
        return heap

    @staticmethod
    def _prepare_back_jump_to_current_address(
        back_jumps, back_jumps_to_patch, i, mgenc
    ):
        while back_jumps and back_jumps[0].address <= i:
            jump = heappop(back_jumps)
            assert (
                jump.address == i
            ), "we use the less or equal, but actually expect it to be strictly equal"
            heappush(
                back_jumps_to_patch,
                _BackJumpPatch(
                    jump.backward_jump_idx, mgenc.offset_of_next_instruction()
                ),
            )

    @staticmethod
    def _patch_jump_to_current_address(i, jumps, mgenc):
        while jumps and jumps[0].address <= i:
            jump = heappop(jumps)
            assert (
                jump.address == i
            ), "we use the less or equal, but actually expect it to be strictly equal"
            mgenc.patch_jump_offset_to_point_to_next_instruction(jump.idx, None)

    def _inline_into(self, mgenc):
        jumps = []  # a sorted list/priority queue. sorted by original_target index
        back_jumps = self._create_back_jump_heap()
        back_jumps_to_patch = []

        i = 0
        while i < len(self._bytecodes):
            self._prepare_back_jump_to_current_address(
                back_jumps, back_jumps_to_patch, i, mgenc
            )
            self._patch_jump_to_current_address(i, jumps, mgenc)

            bytecode = self.get_bytecode(i)
            bc_length = bytecode_length(bytecode)

            if bytecode == Bytecodes.halt:
                emit1(mgenc, bytecode, 0)

            elif bytecode == Bytecodes.dup or bytecode == Bytecodes.dup_second:
                emit1(mgenc, bytecode, 1)

            elif (
                bytecode == Bytecodes.push_field
                or bytecode == Bytecodes.pop_field
                or bytecode == Bytecodes.push_argument
                or bytecode == Bytecodes.pop_argument
            ):
                idx = self.get_bytecode(i + 1)
                ctx_level = self.get_bytecode(i + 2)

                if ctx_level == 0:
                    assert (
                        bytecode == Bytecodes.push_argument
                        or bytecode == Bytecodes.pop_argument
                    ), (
                        "This should really be push or pop argument."
                        + " everything else should have a ctx_level > 0"
                    )

                    arg = self._lexical_scope.get_argument(idx, 0)
                    idx = mgenc.get_inlined_local_idx(arg, 0)
                    if bytecode == Bytecodes.push_argument:
                        emit_push_local(mgenc, idx, 0)
                    else:
                        emit_pop_local(mgenc, idx, 0)
                elif bytecode == Bytecodes.push_field:
                    emit_push_field_with_index(mgenc, idx, ctx_level - 1)
                elif bytecode == Bytecodes.pop_field:
                    emit_pop_field_with_index(mgenc, idx, ctx_level - 1)
                else:
                    emit3(
                        mgenc,
                        bytecode,
                        idx,
                        ctx_level - 1,
                        1 if Bytecodes.push_argument else -1,
                    )
            elif (
                bytecode == Bytecodes.inc_field or bytecode == Bytecodes.inc_field_push
            ):
                idx = self.get_bytecode(i + 1)
                ctx_level = self.get_bytecode(i + 2)
                assert ctx_level > 0
                emit3(mgenc, bytecode, idx, ctx_level - 1, 1)

            elif bytecode == Bytecodes.push_local or bytecode == Bytecodes.pop_local:
                idx = self.get_bytecode(i + 1)
                ctx_level = self.get_bytecode(i + 2)
                if ctx_level == 0:
                    # these have been inlined into the outer context already
                    # so, we need to look up the right one
                    var = self._lexical_scope.get_local(idx, 0)
                    idx = mgenc.get_inlined_local_idx(var, 0)
                else:
                    ctx_level -= 1
                if bytecode == Bytecodes.push_local:
                    emit3(mgenc, bytecode, idx, ctx_level, 1)
                else:
                    emit3(mgenc, bytecode, idx, ctx_level, -1)

            elif bytecode == Bytecodes.nil_local:
                idx = self.get_bytecode(i + 1)
                var = self._lexical_scope.get_local(idx, 0)
                idx = mgenc.get_inlined_local_idx(var, 0)
                emit_nil_local(mgenc, idx)

            elif bytecode == Bytecodes.push_block:
                literal_idx = self.get_bytecode(i + 1)
                block_method = self._literals[literal_idx]
                block_method.adapt_after_outer_inlined(1, mgenc)
                emit_push_block(mgenc, block_method, True)

            elif bytecode == Bytecodes.push_block_no_ctx:
                literal_idx = self.get_bytecode(i + 1)
                block_method = self._literals[literal_idx]
                emit_push_block(mgenc, block_method, False)

            elif bytecode == Bytecodes.push_constant:
                literal_idx = self.get_bytecode(i + 1)
                literal = self._literals[literal_idx]
                emit_push_constant(mgenc, literal)

            elif (
                bytecode == Bytecodes.push_constant_0
                or bytecode == Bytecodes.push_constant_1
                or bytecode == Bytecodes.push_constant_2
            ):
                literal_idx = bytecode - Bytecodes.push_constant_0
                literal = self._literals[literal_idx]
                emit_push_constant(mgenc, literal)

            elif (
                bytecode == Bytecodes.push_0
                or bytecode == Bytecodes.push_1
                or bytecode == Bytecodes.push_nil
            ):
                emit1(mgenc, bytecode, 1)

            elif bytecode == Bytecodes.pop:
                emit1(mgenc, bytecode, -1)

            elif bytecode == Bytecodes.inc or bytecode == Bytecodes.dec:
                emit1(mgenc, bytecode, 0)

            elif bytecode == Bytecodes.push_global:
                literal_idx = self.get_bytecode(i + 1)
                sym = self._literals[literal_idx]
                emit_push_global(mgenc, sym)

            elif (
                bytecode == Bytecodes.send_1
                or bytecode == Bytecodes.send_2
                or bytecode == Bytecodes.send_3
                or bytecode == Bytecodes.send_n
            ):
                literal_idx = self.get_bytecode(i + 1)
                sym = self._literals[literal_idx]
                emit_send(mgenc, sym)

            elif bytecode == Bytecodes.super_send:
                literal_idx = self.get_bytecode(i + 1)
                sym = self._literals[literal_idx]
                emit_super_send(mgenc, sym)

            elif bytecode == Bytecodes.return_local:
                # NO OP, doesn't need to be translated
                pass

            elif bytecode == Bytecodes.return_non_local:
                new_ctx_level = self.get_bytecode(i + 1) - 1
                if new_ctx_level == 0:
                    emit_return_local(mgenc)
                else:
                    assert new_ctx_level == mgenc.get_max_context_level()
                    emit_return_non_local(mgenc)

            elif (
                bytecode == Bytecodes.return_field_0
                or bytecode == Bytecodes.return_field_1
                or bytecode == Bytecodes.return_field_2
            ):
                emit1(mgenc, bytecode, 0)

            elif (
                bytecode == Bytecodes.jump
                or bytecode == Bytecodes.jump_on_true_top_nil
                or bytecode == Bytecodes.jump_on_false_top_nil
                or bytecode == Bytecodes.jump_if_greater
                or bytecode == Bytecodes.jump2
                or bytecode == Bytecodes.jump2_on_true_top_nil
                or bytecode == Bytecodes.jump2_on_false_top_nil
                or bytecode == Bytecodes.jump2_if_greater
            ):
                # emit the jump, but instead of the offset, emit a dummy
                idx = emit3_with_dummy(mgenc, bytecode, 0)
                offset = compute_offset(
                    self.get_bytecode(i + 1), self.get_bytecode(i + 2)
                )
                jump = _Jump(i + offset, bytecode, idx)
                heappush(jumps, jump)
            elif (
                bytecode == Bytecodes.jump_on_true_pop
                or bytecode == Bytecodes.jump_on_false_pop
                or bytecode == Bytecodes.jump2_on_true_pop
                or bytecode == Bytecodes.jump2_on_false_pop
            ):
                # emit the jump, but instead of the offset, emit a dummy
                idx = emit3_with_dummy(mgenc, bytecode, -1)
                offset = compute_offset(
                    self.get_bytecode(i + 1), self.get_bytecode(i + 2)
                )
                jump = _Jump(i + offset, bytecode, idx)
                heappush(jumps, jump)

            elif (
                bytecode == Bytecodes.jump_backward
                or bytecode == Bytecodes.jump2_backward
            ):
                jump = heappop(back_jumps_to_patch)
                assert (
                    jump.address == i
                ), "the jump should match with the jump instructions"
                mgenc.emit_backwards_jump_offset_to_target(jump.loop_begin_idx, None)

            elif bytecode in RUN_TIME_ONLY_BYTECODES:
                raise Exception(
                    "Found an unexpected bytecode. i: "
                    + str(i)
                    + " bytecode: "
                    + bytecode_as_str(bytecode)
                )

            elif bytecode in NOT_EXPECTED_IN_BLOCK_BYTECODES:
                raise Exception(
                    "Found "
                    + bytecode_as_str(bytecode)
                    + " bytecode, but it's not expected in a block method"
                )
            else:
                raise Exception(
                    "Found "
                    + bytecode_as_str(bytecode)
                    + " bytecode, but inlining does not handle it yet."
                )

            i += bc_length

        assert not jumps

    def adapt_after_outer_inlined(self, removed_ctx_level, mgenc_with_inlined):
        i = 0
        while i < len(self._bytecodes):
            bytecode = self.get_bytecode(i)
            bc_length = bytecode_length(bytecode)

            if (
                bytecode == Bytecodes.halt
                or bytecode == Bytecodes.dup
                or bytecode == Bytecodes.dup_second
                or bytecode == Bytecodes.push_block_no_ctx
                or bytecode == Bytecodes.push_constant
                or bytecode == Bytecodes.push_constant_0
                or bytecode == Bytecodes.push_constant_1
                or bytecode == Bytecodes.push_constant_2
                or bytecode == Bytecodes.push_0
                or bytecode == Bytecodes.push_1
                or bytecode == Bytecodes.push_nil
                or bytecode == Bytecodes.push_global
                or bytecode == Bytecodes.pop  # push_global doesn't encode context
                or bytecode == Bytecodes.send_1
                or bytecode == Bytecodes.send_2
                or bytecode == Bytecodes.send_3
                or bytecode == Bytecodes.send_n
                or bytecode == Bytecodes.super_send
                or bytecode == Bytecodes.return_local
                or bytecode == Bytecodes.return_field_0
                or bytecode == Bytecodes.return_field_1
                or bytecode == Bytecodes.return_field_2
                or bytecode == Bytecodes.inc
                or bytecode == Bytecodes.dec
                or bytecode == Bytecodes.jump
                or bytecode == Bytecodes.jump_on_true_top_nil
                or bytecode == Bytecodes.jump_on_true_pop
                or bytecode == Bytecodes.jump_on_false_top_nil
                or bytecode == Bytecodes.jump_on_false_pop
                or bytecode == Bytecodes.jump_if_greater
                or bytecode == Bytecodes.jump_backward
                or bytecode == Bytecodes.jump2
                or bytecode == Bytecodes.jump2_on_true_top_nil
                or bytecode == Bytecodes.jump2_on_true_pop
                or bytecode == Bytecodes.jump2_on_false_top_nil
                or bytecode == Bytecodes.jump2_on_false_pop
                or bytecode == Bytecodes.jump2_if_greater
                or bytecode == Bytecodes.jump2_backward
            ):
                # don't use context
                pass

            elif (
                bytecode == Bytecodes.push_field
                or bytecode == Bytecodes.pop_field
                or bytecode == Bytecodes.push_argument
                or bytecode == Bytecodes.pop_argument
                or bytecode == Bytecodes.inc_field_push
                or bytecode == Bytecodes.inc_field
            ):
                ctx_level = self.get_bytecode(i + 2)
                if ctx_level > removed_ctx_level:
                    self.set_bytecode(i + 2, ctx_level - 1)
                elif ctx_level == removed_ctx_level and (
                    bytecode == Bytecodes.push_argument
                    or bytecode == Bytecodes.pop_argument
                ):
                    idx = self.get_bytecode(i + 1)
                    arg = self._lexical_scope.get_argument(idx, removed_ctx_level)
                    new_idx = mgenc_with_inlined.get_inlined_local_idx(
                        arg, removed_ctx_level
                    )
                    if bytecode == Bytecodes.push_argument:
                        self.set_bytecode(i, Bytecodes.push_local)
                    else:
                        self.set_bytecode(i, Bytecodes.pop_local)
                    self.set_bytecode(i + 1, new_idx)

            elif bytecode == Bytecodes.push_block:
                literal_idx = self.get_bytecode(i + 1)
                block_method = self._literals[literal_idx]
                block_method.adapt_after_outer_inlined(
                    removed_ctx_level + 1, mgenc_with_inlined
                )

            elif bytecode == Bytecodes.push_local or bytecode == Bytecodes.pop_local:
                ctx_level = self.get_bytecode(i + 2)
                if ctx_level == removed_ctx_level:
                    idx = self.get_bytecode(i + 1)
                    # locals have been inlined into the outer context already
                    # so, we need to look up the right one and fix up the index
                    # at this point, the lexical scope has not been changed
                    # so, we should still be able to find the right one
                    old_var = self._lexical_scope.get_local(idx, ctx_level)
                    new_idx = mgenc_with_inlined.get_inlined_local_idx(
                        old_var, ctx_level
                    )
                    self.set_bytecode(i + 1, new_idx)
                elif ctx_level > removed_ctx_level:
                    self.set_bytecode(i + 2, ctx_level - 1)

            elif bytecode == Bytecodes.nil_local:
                assert removed_ctx_level > 0, (
                    "Don't need to adjust this bytecode, "
                    + "because it only operates on ctx_level==0"
                )

            elif bytecode == Bytecodes.return_non_local:
                ctx_level = self.get_bytecode(i + 1)
                self.set_bytecode(i + 1, ctx_level - 1)

            elif bytecode in RUN_TIME_ONLY_BYTECODES:
                raise Exception(
                    "Found an unexpected bytecode. i: "
                    + str(i)
                    + " bytecode: "
                    + bytecode_as_str(bytecode)
                )

            elif bytecode in NOT_EXPECTED_IN_BLOCK_BYTECODES:
                raise Exception(
                    "Found "
                    + bytecode_as_str(bytecode)
                    + " bytecode, but it's not expected in a block method"
                )
            else:
                raise Exception(
                    "Found "
                    + bytecode_as_str(bytecode)
                    + " bytecode, but adapt_after_outer_inlined does not handle it yet."
                )

            i += bc_length

        if removed_ctx_level == 1:
            self._lexical_scope.drop_inlined_scope()


class _Jump(HeapEntry):
    def __init__(self, jump_target, bytecode, idx):
        HeapEntry.__init__(self, jump_target)
        self.bytecode = bytecode
        self.idx = idx


class BackJump(HeapEntry):
    def __init__(self, loop_begin_idx, backward_jump_idx):
        HeapEntry.__init__(self, loop_begin_idx)
        self.backward_jump_idx = backward_jump_idx


class _BackJumpPatch(HeapEntry):
    def __init__(self, backward_jump_idx, loop_begin_idx):
        HeapEntry.__init__(self, backward_jump_idx)
        self.loop_begin_idx = loop_begin_idx


class BcMethodNLR(BcMethod):
    def invoke_1(self, rcvr):
        new_frame = create_frame_1(rcvr, self._size_frame, self._size_inner)
        return _interp_with_nlr(self, new_frame, self._maximum_number_of_stack_elements)

    def invoke_2(self, rcvr, arg1):
        new_frame = create_frame_2(
            rcvr,
            arg1,
            self._arg_inner_access[0],
            self._size_frame,
            self._size_inner,
        )
        return _interp_with_nlr(self, new_frame, self._maximum_number_of_stack_elements)

    def invoke_3(self, rcvr, arg1, arg2):
        new_frame = create_frame_3(
            self._arg_inner_access,
            self._size_frame,
            self._size_inner,
            rcvr,
            arg1,
            arg2,
        )
        return _interp_with_nlr(self, new_frame, self._maximum_number_of_stack_elements)

    def invoke_n(self, stack, stack_ptr):
        new_frame = create_frame(
            self._arg_inner_access,
            self._size_frame,
            self._size_inner,
            stack,
            stack_ptr,
            self._number_of_arguments,
        )
        inner = get_inner_as_context(new_frame)

        try:
            result = interpret(self, new_frame, self._maximum_number_of_stack_elements)
            stack_ptr = stack_pop_old_arguments_and_push_result(
                stack, stack_ptr, self._number_of_arguments, result
            )
            mark_as_no_longer_on_stack(inner)
            return stack_ptr
        except ReturnException as e:
            mark_as_no_longer_on_stack(inner)
            if e.has_reached_target(inner):
                return stack_pop_old_arguments_and_push_result(
                    stack, stack_ptr, self._number_of_arguments, e.get_result()
                )
            raise e

    def inline(self, mgenc, merge_scope=True):
        raise Exception(
            "Blocks should never handle non-local returns. "
            "So, this should not happen."
        )
