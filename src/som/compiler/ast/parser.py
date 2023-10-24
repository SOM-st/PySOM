from som.compiler.ast.method_generation_context import MethodGenerationContext
from som.compiler.parse_error import ParseError
from som.compiler.parser import ParserBase
from som.compiler.symbol import Symbol

from som.interpreter.ast.nodes.block_node import BlockNode, BlockNodeWithContext
from som.interpreter.ast.nodes.literal_node import LiteralNode
from som.interpreter.ast.nodes.message.super_node import (
    UnarySuper,
    BinarySuper,
    TernarySuper,
    NArySuper,
)
from som.interpreter.ast.nodes.message.uninitialized_node import (
    UninitializedMessageNode,
)
from som.interpreter.ast.nodes.return_non_local_node import ReturnNonLocalNode
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
from som.vm.symbols import symbol_for

from som.vmobjects.array import Array
from som.vmobjects.string import String


class Parser(ParserBase):
    def __init__(self, reader, file_name, universe):
        ParserBase.__init__(self, reader, file_name, universe)

    def _assign_source(self, node, coord):
        node.assign_source_section(self._get_source_section(coord))
        return node

    def _method_block(self, mgenc):
        self._expect(Symbol.NewTerm)
        method_body = self._block_contents(mgenc)
        self._expect(Symbol.EndTerm)
        return method_body

    def _block_body(self, mgenc, _seen_period):
        coordinate = self._lexer.get_source_coordinate()
        expressions = []

        while True:
            if self._accept(Symbol.Exit):
                expressions.append(self._result(mgenc))
                return self._create_sequence_node(coordinate, expressions)
            if self._sym == Symbol.EndBlock:
                return self._create_sequence_node(coordinate, expressions)
            if self._sym == Symbol.EndTerm:
                # the end of the method has been found (EndTerm) - make it
                # implicitly return "self"
                self_exp = self._variable_read(mgenc, "self")
                self_coord = self._lexer.get_source_coordinate()
                self._assign_source(self_exp, self_coord)
                expressions.append(self_exp)
                return self._create_sequence_node(coordinate, expressions)

            expressions.append(self._expression(mgenc))
            self._accept(Symbol.Period)

    def _create_sequence_node(self, coordinate, expressions):
        if not expressions:
            from som.vm.globals import nilObject

            return LiteralNode(nilObject, self._get_source_section(coordinate))
        if len(expressions) == 1:
            return expressions[0]

        return SequenceNode(expressions[:], self._get_source_section(coordinate))

    def _result(self, mgenc):
        exp = self._expression(mgenc)
        coord = self._lexer.get_source_coordinate()

        self._accept(Symbol.Period)

        if mgenc.is_block_method:
            node = ReturnNonLocalNode(
                mgenc.get_outer_self_context_level(), exp, self.universe
            )
            mgenc.make_catch_non_local_return()
            return self._assign_source(node, coord)
        return exp

    def _assignation(self, mgenc):
        return self._assignments(mgenc)

    def _assignments(self, mgenc):
        coord = self._lexer.get_source_coordinate()

        if not self._sym_is_identifier():
            raise ParseError(
                "Assignments should always target variables or"
                " fields, but found instead a %(found)s",
                Symbol.Identifier,
                self,
            )

        variable = self._assignment()
        self._peek_for_next_symbol_from_lexer()

        if self._next_sym == Symbol.Assign:
            value = self._assignments(mgenc)
        else:
            value = self._evaluation(mgenc)

        exp = self._variable_write(mgenc, variable, value)
        return self._assign_source(exp, coord)

    def _assignment(self):
        var_name = self._variable()
        self._expect(Symbol.Assign)
        return var_name

    def _evaluation(self, mgenc):
        exp = self._primary(mgenc)

        if (
            self._sym_is_identifier()
            or self._sym == Symbol.Keyword
            or self._sym == Symbol.OperatorSequence
            or self._sym_in(self._binary_op_syms)
        ):
            exp = self._messages(mgenc, exp)

        self._super_send = False
        return exp

    def _primary(self, mgenc):
        if self._sym_is_identifier():
            coordinate = self._lexer.get_source_coordinate()
            var_name = self._variable()
            if var_name == "super":
                self._super_send = True
                # sends to super push self as the receiver
                var_name = "self"
            var_read = self._variable_read(mgenc, var_name)
            return self._assign_source(var_read, coordinate)

        if self._sym == Symbol.NewTerm:
            return self._nested_term(mgenc)

        if self._sym == Symbol.NewBlock:
            coordinate = self._lexer.get_source_coordinate()
            bgenc = MethodGenerationContext(self.universe, mgenc.holder, mgenc)

            block_body = self.nested_block(bgenc)
            block_method = bgenc.assemble(block_body)
            mgenc.add_embedded_block_method(block_method)

            if bgenc.requires_context():
                result = BlockNodeWithContext(block_method, self.universe)
            else:
                result = BlockNode(block_method, self.universe)
            return self._assign_source(result, coordinate)

        return self._literal()

    def _messages(self, mgenc, receiver):
        msg = receiver

        while self._sym_is_identifier():
            msg = self._unary_message(mgenc, msg)

        while self._sym == Symbol.OperatorSequence or self._sym_in(
            self._binary_op_syms
        ):
            msg = self._binary_message(mgenc, msg)

        if self._sym == Symbol.Keyword:
            msg = self._keyword_message(mgenc, msg)

        return msg

    def _unary_message(self, mgenc, receiver):
        is_super_send = self._super_send
        self._super_send = False

        coord = self._lexer.get_source_coordinate()
        selector = self._unary_selector()

        if is_super_send:
            msg = UnarySuper(selector, receiver, mgenc.holder.get_super_class())
        else:
            msg = UninitializedMessageNode(selector, self.universe, receiver, [])
        return self._assign_source(msg, coord)

    def _binary_message(self, mgenc, receiver):
        is_super_send = self._super_send
        self._super_send = False

        coord = self._lexer.get_source_coordinate()
        selector = self._binary_selector()
        arg_expr = self._binary_operand(mgenc)

        source = self._get_source_section(coord)

        if not is_super_send:
            sel = selector.get_embedded_string()
            if sel == "&&":
                inlined = self._try_inlining_and(receiver, arg_expr, source, mgenc)
                if inlined is not None:
                    return inlined
            elif sel == "||":
                inlined = self._try_inlining_or(receiver, arg_expr, source, mgenc)
                if inlined is not None:
                    return inlined

        if is_super_send:
            return BinarySuper(
                selector, receiver, arg_expr, mgenc.holder.get_super_class(), source
            )
        if selector.get_embedded_string() == "+" and isinstance(arg_expr, LiteralNode):
            lit_val = arg_expr.execute(None)
            from som.vmobjects.integer import Integer

            if isinstance(lit_val, Integer) and lit_val.get_embedded_integer() == 1:
                return IntIncrementNode(receiver, source)

        return UninitializedMessageNode(
            selector, self.universe, receiver, [arg_expr], source
        )

    def _binary_operand(self, mgenc):
        operand = self._primary(mgenc)

        while self._sym_is_identifier():
            operand = self._unary_message(mgenc, operand)

        return operand

    @staticmethod
    def _try_inlining_if(if_true, receiver, arguments, source, mgenc):
        arg = arguments[0]
        if not isinstance(arg, BlockNode):
            return None

        method = arg.get_method()
        body_expr = method.inline(mgenc)
        return IfInlinedNode(receiver, body_expr, if_true, source)

    @staticmethod
    def _try_inlining_if_else(if_true, receiver, arguments, source, mgenc):
        arg1 = arguments[0]
        if not isinstance(arg1, BlockNode):
            return None

        arg2 = arguments[1]
        if not isinstance(arg2, BlockNode):
            return None

        true_expr = arg1.get_method().inline(mgenc)
        false_expr = arg2.get_method().inline(mgenc)
        return IfElseInlinedNode(receiver, true_expr, false_expr, if_true, source)

    @staticmethod
    def _try_inlining_while(while_true, receiver, arguments, source, mgenc):
        if not isinstance(receiver, BlockNode):
            return None

        if not isinstance(arguments[0], BlockNode):
            return None

        cond_expr = receiver.get_method().inline(mgenc)
        body_expr = arguments[0].get_method().inline(mgenc)
        return WhileInlinedNode(cond_expr, body_expr, while_true, source)

    @staticmethod
    def _try_inlining_and(receiver, arg_expr, source, mgenc):
        if not isinstance(arg_expr, BlockNode):
            return None

        arg_body = arg_expr.get_method().inline(mgenc)
        return AndInlinedNode(receiver, arg_body, source)

    @staticmethod
    def _try_inlining_or(receiver, arg_expr, source, mgenc):
        if not isinstance(arg_expr, BlockNode):
            return None

        arg_body = arg_expr.get_method().inline(mgenc)
        return OrInlinedNode(receiver, arg_body, source)

    @staticmethod
    def _try_inlining_to_do(receiver, arguments, source, mgenc):
        if not isinstance(arguments[1], BlockNode):
            return None

        block_method = arguments[1].get_method()
        do_expr = block_method.inline(mgenc)
        idx_arg = block_method.get_argument(1, 0)
        return ToDoInlined(
            receiver, arguments[0], do_expr, mgenc.get_inlined_local(idx_arg, 0), source
        )

    def _keyword_message(self, mgenc, receiver):
        is_super_send = self._super_send

        coord = self._lexer.get_source_coordinate()
        arguments = []
        keyword_parts = []

        while self._sym == Symbol.Keyword:
            keyword_parts.append(self._keyword())
            arguments.append(self._formula(mgenc))

        keyword = "".join(keyword_parts)
        source = self._get_source_section(coord)

        num_args = len(arguments)

        if not is_super_send:
            if num_args == 1:
                if keyword == "ifTrue:":
                    inlined = self._try_inlining_if(
                        True, receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "ifFalse:":
                    inlined = self._try_inlining_if(
                        False, receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "whileTrue:":
                    inlined = self._try_inlining_while(
                        True, receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "whileFalse:":
                    inlined = self._try_inlining_while(
                        False, receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "and:":
                    inlined = self._try_inlining_and(
                        receiver, arguments[0], source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "or:":
                    inlined = self._try_inlining_or(
                        receiver, arguments[0], source, mgenc
                    )
                    if inlined is not None:
                        return inlined
            elif num_args == 2:
                if keyword == "ifTrue:ifFalse:":
                    inlined = self._try_inlining_if_else(
                        True, receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "ifFalse:ifTrue:":
                    inlined = self._try_inlining_if_else(
                        False, receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined
                elif keyword == "to:do:":
                    inlined = self._try_inlining_to_do(
                        receiver, arguments, source, mgenc
                    )
                    if inlined is not None:
                        return inlined

        selector = symbol_for(keyword)

        if is_super_send:
            num_args = len(arguments) + 1
            if num_args == 2:
                msg = BinarySuper(
                    selector, receiver, arguments[0], mgenc.holder.get_super_class()
                )
            elif num_args == 3:
                msg = TernarySuper(
                    selector,
                    receiver,
                    arguments[0],
                    arguments[1],
                    mgenc.holder.get_super_class(),
                )
            else:
                msg = NArySuper(
                    selector, receiver, arguments[:], mgenc.holder.get_super_class()
                )
        else:
            msg = UninitializedMessageNode(
                selector, self.universe, receiver, arguments[:]
            )
        return self._assign_source(msg, coord)

    def _formula(self, mgenc):
        operand = self._binary_operand(mgenc)

        while self._sym == Symbol.OperatorSequence or self._sym_in(
            self._binary_op_syms
        ):
            operand = self._binary_message(mgenc, operand)

        self._super_send = False
        return operand

    def _literal(self):
        coord = self._lexer.get_source_coordinate()
        val = self._get_object_for_current_literal()

        lit = LiteralNode(val, self._get_source_section(coord))
        return lit

    def _get_object_for_current_literal(self):
        if self._sym == Symbol.Pound:
            self._peek_for_next_symbol_from_lexer_if_necessary()

            if self._next_sym == Symbol.NewTerm:
                return self._literal_array()
            return self._literal_symbol()
        if self._sym == Symbol.STString:
            return self._literal_string()
        return self._literal_number()

    def _literal_number(self):
        if self._sym == Symbol.Minus:
            return self._negative_decimal()
        return self._literal_decimal(False)

    def _literal_symbol(self):
        self._expect(Symbol.Pound)
        if self._sym == Symbol.STString:
            s = self._string()
            return symbol_for(s)
        return self._selector()

    def _literal_string(self):
        s = self._string()
        return String(s)

    def _literal_array(self):
        literals = []
        self._expect(Symbol.Pound)
        self._expect(Symbol.NewTerm)
        while self._sym != Symbol.EndTerm:
            literals.append(self._get_object_for_current_literal())
        self._expect(Symbol.EndTerm)
        return Array.from_values(literals[:])

    def nested_block(self, mgenc):
        self._nested_block_signature(mgenc)
        expressions = self._block_contents(mgenc)
        self._expect(Symbol.EndBlock)
        return expressions

    @staticmethod
    def _variable_read(mgenc, variable_name):
        # first lookup in local variables, or method arguments
        variable = mgenc.get_variable(variable_name)
        if variable:
            return variable.get_read_node(mgenc.get_context_level(variable_name))

        # otherwise, it might be an object field
        var_symbol = symbol_for(variable_name)
        field_read = mgenc.get_object_field_read(var_symbol)
        if field_read:
            return field_read

        # nope, so, it is a global?
        return mgenc.get_global_read(var_symbol)

    def _variable_write(self, mgenc, variable_name, exp):
        if variable_name == "self":
            raise ParseError(
                "It is not possible to write to `self`, it is a pseudo variable",
                Symbol.NONE,
                self,
            )
        if variable_name == "super":
            raise ParseError(
                "It is not possible to write to `super`, it is a pseudo variable",
                Symbol.NONE,
                self,
            )

        variable = mgenc.get_variable(variable_name)
        if variable:
            return variable.get_write_node(mgenc.get_context_level(variable_name), exp)

        field_name = symbol_for(variable_name)
        field_write = mgenc.get_object_field_write(field_name, exp)
        if field_write:
            return field_write
        raise RuntimeError(
            "Neither a variable nor a field found in current"
            " scope that is named " + variable_name + "."
        )
