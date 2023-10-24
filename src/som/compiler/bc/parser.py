from som.compiler.bc.bytecode_generator import (
    emit_inc,
    emit_dec,
    emit_dup,
    emit_pop,
    emit_send,
    emit_pop_field,
    emit_pop_local,
    emit_return_local,
    emit_return_self,
    emit_super_send,
    emit_push_field,
    emit_push_global,
    emit_push_block,
    emit_push_local,
    emit_push_argument,
    emit_pop_argument,
    emit_push_constant,
    emit_push_constant_index,
    emit_return_non_local,
)
from som.compiler.bc.method_generation_context import MethodGenerationContext
from som.compiler.parser import ParserBase
from som.compiler.symbol import Symbol
from som.vm.symbols import (
    sym_array,
    sym_array_size_placeholder,
    sym_new_msg,
    sym_at_put_msg,
    symbol_for,
    sym_minus,
    sym_plus,
)
from som.vmobjects.integer import Integer
from som.vmobjects.string import String


class Parser(ParserBase):
    def __init__(self, reader, file_name, universe):
        ParserBase.__init__(self, reader, file_name, universe)

    def _method_block(self, mgenc):
        self._expect(Symbol.NewTerm)
        self._block_contents(mgenc)

        # if no return has been generated so far, we can be sure there was no .
        # terminating the last expression, so the last expression's value must
        # be popped off the stack and a ^self be generated
        if not mgenc.is_finished():
            # with RETURN_SELF, we don't need the extra stack space
            # self._bc_gen.emitPOP(mgenc)
            emit_return_self(mgenc)
            mgenc.set_finished()

        self._expect(Symbol.EndTerm)

    def _block_body(self, mgenc, seen_period):
        if self._accept(Symbol.Exit):
            self._result(mgenc)
        elif self._sym == Symbol.EndBlock:
            if seen_period:
                # a POP has been generated which must be elided (blocks always
                # return the value of the last expression, regardless of
                # whether it was terminated with a . or not)
                mgenc.remove_last_pop_for_block_local_return()

            # if this block is empty, we need to return nil
            if mgenc.is_block_method and not mgenc.has_bytecode():
                from som.vm.globals import nilObject

                emit_push_constant(mgenc, nilObject)

            emit_return_local(mgenc)
            mgenc.set_finished()
        elif self._sym == Symbol.EndTerm:
            # it does not matter whether a period has been seen, as the end of
            # the method has been found (EndTerm) - so it is safe to emit a
            # "return self"
            emit_return_self(mgenc)
            mgenc.set_finished()
        else:
            self._expression(mgenc)
            if self._accept(Symbol.Period):
                emit_pop(mgenc)
                self._block_body(mgenc, True)

    def _result(self, mgenc):
        # try to parse a `^ self` to emit RETURN_SELF
        if (
            not mgenc.is_block_method
            and self._sym == Symbol.Identifier
            and self._text == "self"
        ):
            self._peek_for_next_symbol_from_lexer_if_necessary()
            if self._next_sym == Symbol.Period or self._next_sym == Symbol.EndTerm:
                self._expect(Symbol.Identifier)

                emit_return_self(mgenc)
                mgenc.set_finished()

                self._accept(Symbol.Period)
                return

        self._expression(mgenc)
        self._accept(Symbol.Period)

        if mgenc.is_block_method:
            emit_return_non_local(mgenc)
            mgenc.make_catch_non_local_return()
        else:
            emit_return_local(mgenc)

        mgenc.set_finished()

    def _assignation(self, mgenc):
        assignments = []

        self._assignments(mgenc, assignments)
        self._evaluation(mgenc)

        for _assignment in assignments:
            emit_dup(mgenc)

        for assignment in assignments:
            self._gen_pop_variable(mgenc, assignment)

    def _assignments(self, mgenc, assignments):
        if self._sym_is_identifier():
            assignments.append(self._assignment(mgenc))
            self._peek_for_next_symbol_from_lexer()
            if self._next_sym == Symbol.Assign:
                self._assignments(mgenc, assignments)

    def _assignment(self, mgenc):
        variable = self._variable()
        var = symbol_for(variable)
        mgenc.add_literal_if_absent(var)

        self._expect(Symbol.Assign)
        return variable

    def _evaluation(self, mgenc):
        self._primary(mgenc)

        if (
            self._sym_is_identifier()
            or self._sym == Symbol.Keyword
            or self._sym == Symbol.OperatorSequence
            or self._sym_in(self._binary_op_syms)
        ):
            self._messages(mgenc)

        self._super_send = False

    def _primary(self, mgenc):
        if self._sym_is_identifier():
            var_name = self._variable()
            if var_name == "super":
                self._super_send = True
                # sends to super push self as the receiver
                var_name = "self"
            self._gen_push_variable(mgenc, var_name)

        elif self._sym == Symbol.NewTerm:
            self._nested_term(mgenc)
        elif self._sym == Symbol.NewBlock:
            bgenc = MethodGenerationContext(self.universe, mgenc.holder, mgenc)
            self.nested_block(bgenc)

            block_method = bgenc.assemble(None)
            emit_push_block(mgenc, block_method, bgenc.requires_context())
        else:
            self._literal(mgenc)

    def _messages(self, mgenc):
        if self._sym_is_identifier():
            while self._sym_is_identifier():
                # only the first message in a sequence can be a super send
                self._unary_message(mgenc)

            while self._sym == Symbol.OperatorSequence or self._sym_in(
                self._binary_op_syms
            ):
                self._binary_message(mgenc)

            if self._sym == Symbol.Keyword:
                self._keyword_message(mgenc)

        elif self._sym == Symbol.OperatorSequence or self._sym_in(self._binary_op_syms):
            while self._sym == Symbol.OperatorSequence or self._sym_in(
                self._binary_op_syms
            ):
                # only the first message in a sequence can be a super send
                self._binary_message(mgenc)

            if self._sym == Symbol.Keyword:
                self._keyword_message(mgenc)

        else:
            self._keyword_message(mgenc)

    def _unary_message(self, mgenc):
        is_super_send = self._super_send
        self._super_send = False

        msg = self._unary_selector()

        if is_super_send:
            emit_super_send(mgenc, msg)
        else:
            emit_send(mgenc, msg)

    def _try_inc_or_dec_bytecodes(self, msg, is_super_send, mgenc):
        is_inc_or_dec = msg is sym_plus or msg is sym_minus
        if is_inc_or_dec and not is_super_send:
            if self._sym == Symbol.Integer and self._text == "1":
                self._expect(Symbol.Integer)
                if msg is sym_plus:
                    emit_inc(mgenc)
                else:
                    emit_dec(mgenc)
                return True
        return False

    def _binary_message(self, mgenc):
        is_super_send = self._super_send
        self._super_send = False

        msg = self._binary_selector()

        if self._try_inc_or_dec_bytecodes(msg, is_super_send, mgenc):
            return

        self._binary_operand(mgenc)

        if not is_super_send and (
            msg.get_embedded_string() == "||"
            and mgenc.inline_andor(self, True)
            or msg.get_embedded_string() == "&&"
            and mgenc.inline_andor(self, False)
        ):
            return

        if is_super_send:
            emit_super_send(mgenc, msg)
        else:
            emit_send(mgenc, msg)

    def _binary_operand(self, mgenc):
        self._primary(mgenc)

        while self._sym_is_identifier():
            self._unary_message(mgenc)

    def _keyword_message(self, mgenc):
        is_super_send = self._super_send
        self._super_send = False

        keyword_parts = [self._keyword()]
        self._formula(mgenc)

        while self._sym == Symbol.Keyword:
            keyword_parts.append(self._keyword())
            self._formula(mgenc)

        keyword = "".join(keyword_parts)

        num_args = len(keyword_parts)

        if not is_super_send:
            if num_args == 1 and (
                (keyword == "ifTrue:" and mgenc.inline_if_true_or_if_false(self, True))
                or (
                    keyword == "ifFalse:"
                    and mgenc.inline_if_true_or_if_false(self, False)
                )
                or (keyword == "whileTrue:" and mgenc.inline_while(self, True))
                or (keyword == "whileFalse:" and mgenc.inline_while(self, False))
                or (keyword == "or:" and mgenc.inline_andor(self, True))
                or (keyword == "and:" and mgenc.inline_andor(self, False))
            ):
                return

            if num_args == 2 and (
                (
                    keyword == "ifTrue:ifFalse:"
                    and mgenc.inline_if_true_false(self, True)
                )
                or (
                    keyword == "ifFalse:ifTrue:"
                    and mgenc.inline_if_true_false(self, False)
                )
                or (keyword == "to:do:" and mgenc.inline_to_do(self))
            ):
                return

        msg = symbol_for(keyword)

        if is_super_send:
            emit_super_send(mgenc, msg)
        else:
            emit_send(mgenc, msg)

    def _formula(self, mgenc):
        self._binary_operand(mgenc)

        # only the first message in a sequence can be a super send
        if self._sym == Symbol.OperatorSequence or self._sym_in(self._binary_op_syms):
            self._binary_message(mgenc)

        while self._sym == Symbol.OperatorSequence or self._sym_in(
            self._binary_op_syms
        ):
            self._binary_message(mgenc)

        self._super_send = False

    def _literal(self, mgenc):
        if self._sym == Symbol.Pound:
            self._peek_for_next_symbol_from_lexer_if_necessary()

            if self._next_sym == Symbol.NewTerm:
                self._literal_array(mgenc)
            else:
                self._literal_symbol(mgenc)
        elif self._sym == Symbol.STString:
            self._literal_string(mgenc)
        else:
            self._literal_number(mgenc)

    def _literal_number(self, mgenc):
        if self._sym == Symbol.Minus:
            lit = self._negative_decimal()
        else:
            lit = self._literal_decimal(False)

        emit_push_constant(mgenc, lit)

    def _literal_symbol(self, mgenc):
        self._expect(Symbol.Pound)
        if self._sym == Symbol.STString:
            s = self._string()
            symb = symbol_for(s)
        else:
            symb = self._selector()

        emit_push_constant(mgenc, symb)

    def _literal_string(self, mgenc):
        s = self._string()

        string = String(s)
        emit_push_constant(mgenc, string)

    def _literal_array(self, mgenc):
        self._expect(Symbol.Pound)
        self._expect(Symbol.NewTerm)

        array_size_literal_idx = mgenc.add_literal(sym_array_size_placeholder)

        # create empty array
        emit_push_global(mgenc, sym_array)
        emit_push_constant_index(mgenc, array_size_literal_idx)
        emit_send(mgenc, sym_new_msg)

        i = 1

        while self._sym != Symbol.EndTerm:
            push_idx = Integer(i)
            emit_push_constant(mgenc, push_idx)

            self._literal(mgenc)
            emit_send(mgenc, sym_at_put_msg)
            i += 1

        mgenc.update_literal(
            sym_array_size_placeholder, array_size_literal_idx, Integer(i - 1)
        )
        self._expect(Symbol.EndTerm)

    def nested_block(self, mgenc):
        self._nested_block_signature(mgenc)
        self._block_contents(mgenc)

        # if no return has been generated, we can be sure that the last
        # expression in the block was not terminated by ., and can generate
        # a return
        if not mgenc.is_finished():
            if not mgenc.has_bytecode():
                from som.vm.globals import nilObject

                emit_push_constant(mgenc, nilObject)
            emit_return_local(mgenc)
            mgenc.set_finished()

        self._expect(Symbol.EndBlock)

    @staticmethod
    def _gen_push_variable(mgenc, var):
        # The purpose of this function is to find out whether the variable to be
        # pushed on the stack is a local variable, argument, or object field.
        # This is done by examining all available lexical contexts, starting with
        # the innermost (i.e., the one represented by mgenc).

        result = mgenc.find_var(var, 0)
        if result is not None:
            if result.is_argument:
                emit_push_argument(mgenc, result.var.idx, result.context)
            else:
                emit_push_local(mgenc, result.var.idx, result.context)
            result.mark_accessed()
        else:
            identifier = symbol_for(var)
            if mgenc.has_field(identifier):
                field_name = identifier
                mgenc.add_literal_if_absent(field_name)
                emit_push_field(mgenc, field_name)
                mgenc.mark_self_as_accessed_from_outer_context()
            else:
                globe = identifier
                emit_push_global(mgenc, globe)

    @staticmethod
    def _gen_pop_variable(mgenc, var):
        # The purpose of this function is to find out whether the variable to be
        # popped off the stack is a local variable, argument, or object field.
        # This is done by examining all available lexical contexts, starting with
        # the innermost (i.e., the one represented by mgenc).

        result = mgenc.find_var(var, 0)
        if result is not None:
            if result.is_argument:
                emit_pop_argument(mgenc, result.var.idx, result.context)
            else:
                emit_pop_local(mgenc, result.var.idx, result.context)
            result.mark_accessed()
        else:
            emit_pop_field(mgenc, symbol_for(var))
            mgenc.mark_self_as_accessed_from_outer_context()
