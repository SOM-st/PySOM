from rlib.debug import make_sure_not_resized
from som.compiler.bc.bytecode_generator import (
    emit_jump_on_bool_with_dummy_offset,
    emit_jump_with_dummy_offset,
    emit_pop,
    emit_push_constant,
    emit_jump_backward_with_offset,
    emit_dup,
    emit_inc,
    emit_dup_second,
    emit_jump_if_greater_with_dummy_offset,
    emit_pop_local,
    emit_nil_local,
    emit_inc_field_push,
    emit_return_field,
)

from som.compiler.method_generation_context import MethodGenerationContextBase
from som.compiler.parse_error import ParseError
from som.interpreter.bc.bytecodes import (
    bytecode_length,
    Bytecodes,
    POP_X_BYTECODES,
    PUSH_CONST_BYTECODES,
    PUSH_FIELD_BYTECODES,
    POP_FIELD_BYTECODES,
    PUSH_BLOCK_BYTECODES,
    bytecode_as_str,
    is_one_of,
    JUMP_BYTECODES,
    NUM_SINGLE_BYTE_JUMP_BYTECODES,
    FIRST_DOUBLE_BYTE_JUMP_BYTECODE,
    RETURN_FIELD_BYTECODES,
)
from som.vm.globals import trueObject, falseObject
from som.vm.symbols import sym_nil, sym_false, sym_true
from som.vmobjects.integer import int_0, int_1
from som.vmobjects.method_trivial import (
    LiteralReturn,
    GlobalRead,
    FieldRead,
    FieldWrite,
)
from som.vmobjects.primitive import empty_primitive
from som.vmobjects.method_bc import (
    BcMethodNLR,
    BcMethod,
    BackJump,
)

_NUM_LAST_BYTECODES = 4


class MethodGenerationContext(MethodGenerationContextBase):
    def __init__(self, universe, holder, outer):
        MethodGenerationContextBase.__init__(self, universe, holder, outer)

        self._literals = []
        self._finished = False
        self._bytecode = []

        # keep a list of arguments and locals for easy access
        # when patching bytecodes on method completion
        self._arg_list = []
        self._local_list = []

        self._last_4_bytecodes = [Bytecodes.invalid] * _NUM_LAST_BYTECODES
        self._is_currently_inlining_a_block = False
        self.inlined_loops = []

        self.max_stack_depth = 0
        self._current_stack_depth = 0

    def get_number_of_locals(self):
        return len(self._local_list)

    def get_number_of_bytecodes(self):
        return len(self._bytecode)

    def get_maximum_number_of_stack_elements(self):
        """Should not be used on the fast path. Really just hear for the disassembler."""
        return self.max_stack_depth

    def get_bytecode(self, idx):
        return self._bytecode[idx]

    def get_holder(self):
        assert self.holder
        return self.holder

    def get_constant(self, bytecode_index):
        # Get the constant associated to a given bytecode index
        return self._literals[self.get_bytecode(bytecode_index + 1)]

    def add_argument(self, arg, source, parser):
        argument = MethodGenerationContextBase.add_argument(self, arg, source, parser)
        self._arg_list.append(argument)
        return argument

    def add_local(self, local_name, source, parser):
        local = MethodGenerationContextBase.add_local(self, local_name, source, parser)
        self._local_list.append(local)
        return local

    def inline_as_locals(self, variables):
        fresh_copies = MethodGenerationContextBase.inline_as_locals(self, variables)
        if fresh_copies:
            self._local_list.extend(fresh_copies)
        return fresh_copies

    def assemble_trivial_method(self):
        return_candidate = self._last_bytecode_is(0, Bytecodes.return_local)
        if return_candidate != Bytecodes.invalid:
            push_candidate = self._last_bytecode_is_one_of(1, PUSH_CONST_BYTECODES)
            if push_candidate != Bytecodes.invalid:
                return self._assemble_literal_return(return_candidate, push_candidate)

            push_candidate = self._last_bytecode_is(1, Bytecodes.push_global)
            if push_candidate != Bytecodes.invalid:
                return self._assemble_global_return(return_candidate, push_candidate)

            push_candidate = self._last_bytecode_is_one_of(1, PUSH_FIELD_BYTECODES)
            if push_candidate != Bytecodes.invalid:
                return self._assemble_field_getter(return_candidate, push_candidate)

        # because we check for return_self here, we don't consider block methods
        return_candidate = self._last_bytecode_is(0, Bytecodes.return_self)
        if return_candidate != Bytecodes.invalid:
            assert not self.is_block_method
            return self._assemble_field_setter(return_candidate)

        return_candidate = self._last_bytecode_is_one_of(0, RETURN_FIELD_BYTECODES)
        if return_candidate != Bytecodes.invalid:
            return self._assemble_field_getter_from_return(return_candidate)

        return None

    def assemble(self, _dummy):
        if self._primitive:
            return empty_primitive(self.signature.get_embedded_string())

        trivial_method = self.assemble_trivial_method()
        if trivial_method is not None:
            return trivial_method

        arg_inner_access, size_frame, size_inner = self.prepare_frame()

        # +2 for buffer for dnu, #escapedBlock, etc.
        max_stack_size = self.max_stack_depth + 2
        num_locals = len(self._locals)

        if len(arg_inner_access) > 1:
            arg_inner_access.reverse()
            # to make the access fast in create_frame
            # reverse things here, if we have more than 1 item
            # then we don't need to mess with the index to access
            # this map
            make_sure_not_resized(arg_inner_access)

        if self.needs_to_catch_non_local_returns:
            bc_method_class = BcMethodNLR
        else:
            bc_method_class = BcMethod

        meth = bc_method_class(
            list(self._literals),
            num_locals,
            max_stack_size,
            len(self._bytecode),
            self.signature,
            arg_inner_access,
            size_frame,
            size_inner,
            self.lexical_scope,
            self.inlined_loops[:],
        )

        # copy bytecodes into method
        i = 0
        for bytecode in self._bytecode:
            meth.set_bytecode(i, bytecode)
            i += 1

        # return the method - the holder field is to be set later on!
        return meth

    def get_argument(self, index, context):
        if context > 0:
            return self.outer_genc.get_argument(index, context - 1)
        return self._arg_list[index]

    def get_local(self, index, context):
        if context > 0:
            return self.outer_genc.get_local(index, context - 1)
        return self._local_list[index]

    def get_inlined_local_idx(self, var, ctx_level):
        for i in range(len(self._local_list) - 1, -1, -1):
            if self._local_list[i].source is var.source:
                self._local_list[i].mark_accessed(ctx_level)
                return i
        raise Exception(
            "Unexpected issue trying to find an inlined variable. "
            + str(var)
            + " could not be found."
        )

    def is_finished(self):
        return self._finished

    def set_finished(self):
        self._finished = True

    def remove_last_pop_for_block_local_return(self):
        if self._last_4_bytecodes[3] == Bytecodes.pop:
            del self._bytecode[-1]
            return

        if (
            self._last_4_bytecodes[3] in POP_X_BYTECODES
            and self._last_4_bytecodes[2] != Bytecodes.dup
        ):
            # we just removed the DUP and didn't emit the POP using optimizeDupPopPopSequence()
            # so, to make blocks work, we need to reintroduce the DUP
            idx = len(self._bytecode) - bytecode_length(self._last_4_bytecodes[3])
            assert idx >= 0
            assert self._bytecode[idx] in POP_X_BYTECODES
            self._bytecode.insert(idx, Bytecodes.dup)

            self._last_4_bytecodes[0] = self._last_4_bytecodes[1]
            self._last_4_bytecodes[1] = self._last_4_bytecodes[2]
            self._last_4_bytecodes[2] = Bytecodes.dup

        if self._last_4_bytecodes[3] == Bytecodes.inc_field:
            # we optimized the sequence to an INC_FIELD, which doesn't modify the stack
            # but since we need the value to return it from the block, we need to push it.
            self._last_4_bytecodes[3] = Bytecodes.inc_field_push

            bc_offset = len(self._bytecode) - 3
            assert bytecode_length(Bytecodes.inc_field_push) == 3
            assert bytecode_length(Bytecodes.inc_field) == 3
            assert self._bytecode[bc_offset] == Bytecodes.inc_field
            self._bytecode[bc_offset] = Bytecodes.inc_field_push

    def add_literal_if_absent(self, lit):
        if lit in self._literals:
            return self._literals.index(lit)

        self._literals.append(lit)
        return len(self._literals) - 1

    def add_literal(self, lit):
        i = len(self._literals)

        assert i < 128
        self._literals.append(lit)

        return i

    def update_literal(self, old_val, index, new_val):
        assert self._literals[index] == old_val
        self._literals[index] = new_val

    def find_var(self, var, ctx_level):
        if var in self._locals:
            return FindVarResult(self._locals[var], ctx_level, False)

        if var in self._arguments:
            return FindVarResult(self._arguments[var], ctx_level, True)

        if self.outer_genc:
            result = self.outer_genc.find_var(var, ctx_level + 1)
            if result:
                self._accesses_variables_of_outer_context = True
            return result
        return None

    def get_max_context_level(self):
        if self.outer_genc is None:
            return 0
        return 1 + self.outer_genc.get_max_context_level()

    def add_bytecode(self, bytecode, stack_effect):
        self._current_stack_depth += stack_effect
        if self._current_stack_depth > self.max_stack_depth:
            self.max_stack_depth = self._current_stack_depth

        self._bytecode.append(bytecode)
        self._last_4_bytecodes[0] = self._last_4_bytecodes[1]
        self._last_4_bytecodes[1] = self._last_4_bytecodes[2]
        self._last_4_bytecodes[2] = self._last_4_bytecodes[3]
        self._last_4_bytecodes[3] = bytecode

    def add_bytecode_argument(self, bytecode):
        self._bytecode.append(bytecode)

    def add_bytecode_argument_and_get_index(self, bytecode):
        idx = len(self._bytecode)
        self._bytecode.append(bytecode)
        return idx

    def has_bytecode(self):
        return len(self._bytecode) > 0

    def find_literal_index(self, lit):
        return self._literals.index(lit)

    def get_bytecodes(self):
        return self._bytecode

    def _last_bytecode_is(self, idx_from_end, candidate):
        actual = self._last_4_bytecodes[_NUM_LAST_BYTECODES - 1 - idx_from_end]
        if candidate == actual:
            return actual
        return Bytecodes.invalid

    def _last_bytecode_is_one_of(self, idx_from_end, candidates):
        actual = self._last_4_bytecodes[_NUM_LAST_BYTECODES - 1 - idx_from_end]
        if actual == Bytecodes.invalid:
            return Bytecodes.invalid

        for c in candidates:
            if c == actual:
                return actual

        return Bytecodes.invalid

    def _get_offset_of_last_bytecode(self, idx_from_end):
        bc_offset = len(self._bytecode)
        for i in range(idx_from_end + 1):
            actual = self._last_4_bytecodes[_NUM_LAST_BYTECODES - 1 - i]
            if actual == Bytecodes.invalid:
                raise Exception("The requested bytecode is not valid")

            bc_offset -= bytecode_length(actual)
        return bc_offset

    def _remove_last_bytecode_at(self, idx_from_end):
        bc_offset = self._get_offset_of_last_bytecode(idx_from_end)
        bc_to_be_removed = self._last_4_bytecodes[
            _NUM_LAST_BYTECODES - 1 - idx_from_end
        ]
        bc_length = bytecode_length(bc_to_be_removed)

        assert bc_length > 0
        assert bc_offset >= 0
        del self._bytecode[bc_offset : bc_offset + bc_length]

    def _remove_last_bytecodes(self, num_bytecodes):
        bytes_to_remove = 0

        for idx_from_end in range(num_bytecodes):
            bytes_to_remove += bytecode_length(
                self._last_4_bytecodes[_NUM_LAST_BYTECODES - 1 - idx_from_end]
            )

        offset = len(self._bytecode) - bytes_to_remove
        assert offset >= 0
        del self._bytecode[offset:]

    def _reset_last_bytecode_buffer(self):
        self._last_4_bytecodes[0] = Bytecodes.invalid
        self._last_4_bytecodes[1] = Bytecodes.invalid
        self._last_4_bytecodes[2] = Bytecodes.invalid
        self._last_4_bytecodes[3] = Bytecodes.invalid

    def optimize_dup_pop_pop_sequence(self):
        # when we are inlining blocks, this already happened
        # and any new opportunities to apply these optimizations are consequently
        # at jump targets for blocks, and we can't remove those
        if self._is_currently_inlining_a_block:
            return False

        if self._last_bytecode_is(0, Bytecodes.inc_field_push) != Bytecodes.invalid:
            return self.optimize_inc_field_push()

        pop_candidate = self._last_bytecode_is_one_of(0, POP_X_BYTECODES)
        if pop_candidate == Bytecodes.invalid:
            return False

        dup_candidate = self._last_bytecode_is(1, Bytecodes.dup)
        if dup_candidate == Bytecodes.invalid:
            return False

        self._remove_last_bytecode_at(1)  # remove DUP bytecode

        # adapt last 4 bytecodes
        assert self._last_4_bytecodes[3] == pop_candidate
        self._last_4_bytecodes[2] = self._last_4_bytecodes[1]
        self._last_4_bytecodes[1] = self._last_4_bytecodes[0]
        self._last_4_bytecodes[0] = Bytecodes.invalid

        return True

    def optimize_inc_field_push(self):
        assert bytecode_length(Bytecodes.inc_field_push) == 3

        bc_idx = len(self._bytecode) - 3
        assert self._bytecode[bc_idx] == Bytecodes.inc_field_push

        self._bytecode[bc_idx] = Bytecodes.inc_field
        self._last_4_bytecodes[3] = Bytecodes.inc_field

        return True

    def optimize_inc_field(self, field_idx, ctx_level):
        """
        Try using a INC_FIELD bytecode instead of the following sequence.

          PUSH_FIELD
          INC
          DUP
          POP_FIELD

        return true, if it optimized it.
        """
        if self._is_currently_inlining_a_block:
            return False

        if self._last_bytecode_is(0, Bytecodes.dup) == Bytecodes.invalid:
            return False

        if self._last_bytecode_is(1, Bytecodes.inc) == Bytecodes.invalid:
            return False

        push_candidate = self._last_bytecode_is_one_of(2, PUSH_FIELD_BYTECODES)
        if push_candidate == Bytecodes.invalid:
            return False

        assert bytecode_length(Bytecodes.dup) == 1
        assert bytecode_length(Bytecodes.inc) == 1
        bc_offset = 1 + 1 + bytecode_length(push_candidate)

        candidate_idx, candidate_ctx = self._get_index_and_ctx_of_last(
            push_candidate, bc_offset
        )
        if candidate_idx == field_idx and candidate_ctx == ctx_level:
            self._remove_last_bytecodes(3)
            self._reset_last_bytecode_buffer()
            emit_inc_field_push(self, field_idx, ctx_level)
            return True
        return False

    def optimize_return_field(self):
        if self._is_currently_inlining_a_block:
            return False

        bytecode = self._last_4_bytecodes[3]
        if bytecode == Bytecodes.push_field_0:
            idx = 0
        elif bytecode == Bytecodes.push_field_1:
            idx = 1
        elif bytecode == Bytecodes.push_field:
            bc_offset = len(self._bytecode)
            ctx = self._bytecode[bc_offset - 1]
            if ctx > 0:
                return False
            idx = self._bytecode[bc_offset - 2]
            if idx > 2:
                return False
        else:
            return False

        self._remove_last_bytecodes(1)
        self._reset_last_bytecode_buffer()
        emit_return_field(self, idx)
        return True

    def _get_index_and_ctx_of_last(self, bytecode, bc_offset):
        if bytecode == Bytecodes.push_field_0:
            return 0, 0
        if bytecode == Bytecodes.push_field_1:
            return 1, 0

        offset = len(self._bytecode) - bc_offset
        assert self._bytecode[offset] == bytecode
        return self._bytecode[offset + 1], self._bytecode[offset + 2]

    def _assemble_literal_return(self, return_candidate, push_candidate):
        if len(self._bytecode) != (
            bytecode_length(push_candidate) + bytecode_length(return_candidate)
        ):
            return None

        source_section = self.lexical_scope.arguments[0].source

        if len(self._literals) == 1:
            return LiteralReturn(self.signature, self._literals[0], source_section)
        if self._bytecode[0] == Bytecodes.push_0:
            return LiteralReturn(self.signature, int_0, source_section)
        if self._bytecode[0] == Bytecodes.push_1:
            return LiteralReturn(self.signature, int_1, source_section)
        if self._bytecode[0] == Bytecodes.push_nil:
            from som.vm.globals import nilObject

            return LiteralReturn(self.signature, nilObject, source_section)
        raise NotImplementedError(
            "Not sure what's going on. Perhaps some new bytecode or unexpected literal?"
        )

    def _assemble_global_return(self, return_candidate, push_candidate):
        if len(self._bytecode) != (
            bytecode_length(push_candidate) + bytecode_length(return_candidate)
        ):
            return None

        if len(self._literals) == 1:
            from som.vmobjects.symbol import Symbol

            global_name = self._literals[0]
            assert isinstance(global_name, Symbol)

            source_section = self.lexical_scope.arguments[0].source

            if global_name is sym_true:
                return LiteralReturn(self.signature, trueObject, source_section)
            if global_name is sym_false:
                return LiteralReturn(self.signature, falseObject, source_section)
            if global_name is sym_nil:
                from som.vm.globals import nilObject

                return LiteralReturn(self.signature, nilObject, source_section)

            return GlobalRead(
                self.signature,
                global_name,
                self.get_max_context_level(),
                self.universe,
            )

        raise NotImplementedError(
            "Not sure what's going on. Perhaps some new bytecode or unexpected literal?"
        )

    def _assemble_field_getter(self, return_candidate, push_candidate):
        if len(self._bytecode) != (
            bytecode_length(push_candidate) + bytecode_length(return_candidate)
        ):
            return None

        if push_candidate == Bytecodes.push_field_0:
            idx = 0
            ctx = 0
        elif push_candidate == Bytecodes.push_field_1:
            idx = 1
            ctx = 0
        else:
            idx = self._bytecode[-3]
            ctx = self._bytecode[-2]

        return FieldRead(self.signature, idx, ctx)

    def _assemble_field_getter_from_return(self, return_candidate):
        if len(self._bytecode) != bytecode_length(return_candidate):
            return None

        if return_candidate == Bytecodes.return_field_0:
            return FieldRead(self.signature, 0, 0)
        if return_candidate == Bytecodes.return_field_1:
            return FieldRead(self.signature, 1, 0)
        assert return_candidate == Bytecodes.return_field_2
        return FieldRead(self.signature, 2, 0)

    def _assemble_field_setter(self, return_candidate):
        pop_candidate = self._last_bytecode_is_one_of(1, POP_FIELD_BYTECODES)
        if pop_candidate == Bytecodes.invalid:
            return None

        push_candidate = self._last_bytecode_is(2, Bytecodes.push_argument)
        if push_candidate == Bytecodes.invalid:
            return None

        pop_len = bytecode_length(pop_candidate)
        assert bytecode_length(Bytecodes.return_self) == 1
        assert bytecode_length(return_candidate) == 1
        return_len = 1

        if len(self._bytecode) != (
            return_len + pop_len + bytecode_length(push_candidate)
        ):
            return None

        if pop_candidate == Bytecodes.pop_field_0:
            field_idx = 0
        elif pop_candidate == Bytecodes.pop_field_1:
            field_idx = 1
        else:
            assert pop_candidate == Bytecodes.pop_field
            field_idx = self._bytecode[-3]

            # context is 0, because we are in a normal method with return_self
            assert self._bytecode[-2] == 0

        arg_idx = self._bytecode[-(pop_len + return_len + 2)]
        return FieldWrite(self.signature, field_idx, arg_idx)

    def inline_if_true_or_if_false(self, parser, is_if_true):
        # HACK: We do assume that the receiver on the stack is a boolean,
        # HACK: similar to the IfTrueIfFalseNode.
        # HACK: We don't support anything but booleans at the moment.
        push_block_candidate = self._last_bytecode_is_one_of(0, PUSH_BLOCK_BYTECODES)
        if push_block_candidate == Bytecodes.invalid:
            return False

        assert bytecode_length(push_block_candidate) == 2
        block_literal_idx = self._bytecode[-1]

        self._remove_last_bytecodes(1)  # remove push_block*

        jump_offset_idx_to_skip_true_branch = emit_jump_on_bool_with_dummy_offset(
            self, is_if_true, False
        )

        # TODO: remove the block from the literal list
        to_be_inlined = self._literals[block_literal_idx]

        self._is_currently_inlining_a_block = True
        to_be_inlined.inline(self)

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_skip_true_branch, parser
        )

        # with the jumping, it's best to prevent any subsequent optimizations here
        # otherwise we may not have the correct jump target
        self._reset_last_bytecode_buffer()

        return True

    def _has_two_literal_block_arguments(self):
        if self._last_bytecode_is_one_of(0, PUSH_BLOCK_BYTECODES) == Bytecodes.invalid:
            return False

        return (
            self._last_bytecode_is_one_of(1, PUSH_BLOCK_BYTECODES) != Bytecodes.invalid
        )

    def inline_if_true_false(self, parser, is_if_true):
        # HACK: We do assume that the receiver on the stack is a boolean,
        # HACK: similar to the IfTrueIfFalseNode.
        # HACK: We don't support anything but booleans at the moment.

        if not self._has_two_literal_block_arguments():
            return False

        assert (
            bytecode_length(Bytecodes.push_block) == 2
            and bytecode_length(Bytecodes.push_block_no_ctx) == 2
        )

        (
            to_be_inlined_1,
            to_be_inlined_2,
        ) = self._extract_block_methods_and_remove_bytecodes()

        jump_offset_idx_to_skip_true_branch = emit_jump_on_bool_with_dummy_offset(
            self, is_if_true, True
        )

        self._is_currently_inlining_a_block = True
        to_be_inlined_1.inline(self)

        jump_offset_idx_to_skip_false_branch = emit_jump_with_dummy_offset(self)

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_skip_true_branch, parser
        )

        # prevent optimizations between blocks to avoid issues with jump targets
        self._reset_last_bytecode_buffer()

        to_be_inlined_2.inline(self)
        self._is_currently_inlining_a_block = False

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_skip_false_branch, parser
        )

        # prevent optimizations messing with the final jump target
        self._reset_last_bytecode_buffer()

        return True

    def _extract_block_methods_and_remove_bytecodes(self):
        block_1_lit_idx = self._bytecode[-3]
        block_2_lit_idx = self._bytecode[-1]

        # grab the blocks' methods for inlining
        to_be_inlined_1 = self._literals[block_1_lit_idx]
        to_be_inlined_2 = self._literals[block_2_lit_idx]

        self._remove_last_bytecodes(2)

        return to_be_inlined_1, to_be_inlined_2

    def inline_while(self, parser, is_while_true):
        if not self._has_two_literal_block_arguments():
            return False

        assert (
            bytecode_length(Bytecodes.push_block) == 2
            and bytecode_length(Bytecodes.push_block_no_ctx) == 2
        )

        cond_method, body_method = self._extract_block_methods_and_remove_bytecodes()

        loop_begin_idx = self.offset_of_next_instruction()

        self._is_currently_inlining_a_block = True
        cond_method.inline(self)

        jump_offset_idx_to_skip_loop_body = emit_jump_on_bool_with_dummy_offset(
            self, is_while_true, True
        )

        body_method.inline(self)

        self._complete_jumps_and_emit_returning_nil(
            parser, loop_begin_idx, jump_offset_idx_to_skip_loop_body
        )

        self._is_currently_inlining_a_block = False

        return True

    def inline_andor(self, parser, is_or):
        # HACK: We do assume that the receiver on the stack is a boolean,
        # HACK: similar to the IfTrueIfFalseNode.
        # HACK: We don't support anything but booleans at the moment.
        push_block_candidate = self._last_bytecode_is_one_of(0, PUSH_BLOCK_BYTECODES)
        if push_block_candidate == Bytecodes.invalid:
            return False

        assert bytecode_length(push_block_candidate) == 2
        block_literal_idx = self._bytecode[-1]

        self._remove_last_bytecodes(1)  # remove push_block*

        jump_offset_idx_to_skip_branch = emit_jump_on_bool_with_dummy_offset(
            self, not is_or, True
        )

        to_be_inlined = self._literals[block_literal_idx]

        self._is_currently_inlining_a_block = True
        to_be_inlined.inline(self)
        self._is_currently_inlining_a_block = False

        jump_offset_idx_to_skip_push_true = emit_jump_with_dummy_offset(self)

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_skip_branch, parser
        )

        emit_push_constant(self, trueObject if is_or else falseObject)

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_skip_push_true, parser
        )

        self._reset_last_bytecode_buffer()

        return True

    def inline_to_do(self, parser):
        # HACK: We do assume that the receiver on the stack is a integer,
        # HACK: similar to the other inlined messages.
        # HACK: We don't support anything but integer at the moment.
        push_block_candidate = self._last_bytecode_is_one_of(0, PUSH_BLOCK_BYTECODES)
        if push_block_candidate == Bytecodes.invalid:
            return False

        assert bytecode_length(push_block_candidate) == 2
        block_literal_idx = self._bytecode[-1]

        to_be_inlined = self._literals[block_literal_idx]
        to_be_inlined.merge_scope_into(self)

        block_arg = to_be_inlined.get_argument(1, 0)
        i_var_idx = self.get_inlined_local_idx(block_arg, 0)

        self._remove_last_bytecodes(1)  # remove push_block*

        self._is_currently_inlining_a_block = True
        emit_dup_second(self)

        emit_nil_local(self, i_var_idx)

        loop_begin_idx = self.offset_of_next_instruction()
        jump_offset_idx_to_end = emit_jump_if_greater_with_dummy_offset(self)

        emit_dup(self)

        emit_pop_local(self, i_var_idx, 0)

        to_be_inlined.inline(self, False)

        emit_pop(self)
        emit_inc(self)

        emit_nil_local(self, i_var_idx)
        self.emit_backwards_jump_offset_to_target(loop_begin_idx, parser)

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_end, parser
        )

        self._is_currently_inlining_a_block = False
        return True

    def _complete_jumps_and_emit_returning_nil(
        self, parser, loop_begin_idx, jump_offset_idx_to_skip_loop_body
    ):
        from som.vm.globals import nilObject

        self._reset_last_bytecode_buffer()

        emit_pop(self)

        self.emit_backwards_jump_offset_to_target(loop_begin_idx, parser)

        self.patch_jump_offset_to_point_to_next_instruction(
            jump_offset_idx_to_skip_loop_body, parser
        )
        emit_push_constant(self, nilObject)
        self._reset_last_bytecode_buffer()

    def emit_backwards_jump_offset_to_target(self, loop_begin_idx, parser):
        address_of_jump = self.offset_of_next_instruction()
        # we are going to jump backward and want a positive value
        # thus we subtract target_address from address_of_jump
        jump_offset = address_of_jump - loop_begin_idx

        self._check_jump_offset(parser, jump_offset, Bytecodes.jump_backward)
        backward_jump_idx = self.offset_of_next_instruction()
        emit_jump_backward_with_offset(self, jump_offset)

        self.inlined_loops.append(BackJump(loop_begin_idx, backward_jump_idx))

    def patch_jump_offset_to_point_to_next_instruction(self, idx_of_offset, parser):
        instruction_start = idx_of_offset - 1
        bytecode = self._bytecode[instruction_start]
        assert is_one_of(bytecode, JUMP_BYTECODES)

        jump_offset = self.offset_of_next_instruction() - instruction_start

        self._check_jump_offset(parser, jump_offset, bytecode)

        if jump_offset <= 0xFF:
            self._bytecode[idx_of_offset] = jump_offset
            self._bytecode[idx_of_offset + 1] = 0
        else:
            # need to use the jump2* version of the bytecode
            if bytecode < FIRST_DOUBLE_BYTE_JUMP_BYTECODE:
                # still need to bump this one up to
                self._bytecode[instruction_start] += NUM_SINGLE_BYTE_JUMP_BYTECODES
            assert is_one_of(self._bytecode[instruction_start], JUMP_BYTECODES)
            self._bytecode[idx_of_offset] = jump_offset & 0xFF
            self._bytecode[idx_of_offset + 1] = jump_offset >> 8

    def offset_of_next_instruction(self):
        return len(self._bytecode)

    @staticmethod
    def _check_jump_offset(parser, jump_offset, bytecode):
        from som.compiler.symbol import Symbol

        if not 0 <= jump_offset <= 0xFFFF:
            raise ParseError(
                "The jump_offset for the "
                + bytecode_as_str(bytecode)
                + " bytecode is out of range: "
                + str(jump_offset),
                Symbol.NONE,
                parser,
            )


class FindVarResult(object):
    def __init__(self, var, context, is_argument):
        self.var = var
        self.context = context
        self.is_argument = is_argument

    def mark_accessed(self):
        self.var.mark_accessed(self.context)
