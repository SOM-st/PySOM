from som.interpreter.ast.frame import (
    read_frame,
    read_inner,
    write_inner,
    write_frame,
    FRAME_AND_INNER_RCVR_IDX,
)
from som.vmobjects.block_ast import AstBlock

from som.interpreter.ast.nodes.contextual_node import ContextualNode
from som.interpreter.ast.nodes.expression_node import ExpressionNode


class UninitializedReadNode(ExpressionNode):
    _immutable_fields_ = ["var", "_context_level"]

    def __init__(self, var, context_level, source_section):
        ExpressionNode.__init__(self, source_section)
        self.var = var
        self._context_level = context_level

    def execute(self, frame):
        return self._specialize().execute(frame)

    def _specialize(self):
        return self.replace(
            self.var.get_initialized_read_node(self._context_level, self.source_section)
        )

    def handle_inlining(self, mgenc):
        if self._context_level == 0:
            self.var = mgenc.get_inlined_local(self.var, 0)
        else:
            self._context_level -= 1

    def handle_outer_inlined(self, removed_ctx_level, mgenc_with_inlined):
        if self._context_level > removed_ctx_level:
            self._context_level -= 1
        elif self._context_level == removed_ctx_level:
            from som.compiler.ast.variable import Local

            # locals have been inlined into the outer context already
            # so, we need to look up the right one and fix up the index
            # at this point, the lexical scope has not been changed
            # so, we should still be able to find the right one
            assert isinstance(
                self.var, Local
            ), "We are not currently inlining any blocks with arguments"
            self.var = mgenc_with_inlined.get_inlined_local(
                self.var, self._context_level
            )

    def __str__(self):
        return "UninitReadNode(" + str(self.var) + ")"


class UninitializedWriteNode(ExpressionNode):
    _immutable_fields_ = ["_var", "_context_level", "_value_expr?"]
    _child_nodes_ = ["_value_expr"]

    def __init__(self, var, context_level, value_expr, source_section):
        ExpressionNode.__init__(self, source_section)
        self._var = var
        self._context_level = context_level
        self._value_expr = value_expr

    def execute(self, frame):
        return self._specialize().execute(frame)

    def write_value(self, frame, value):
        self._specialize().write_value(frame, value)

    def _specialize(self):
        return self.replace(
            self._var.get_initialized_write_node(
                self._context_level, self._value_expr, self.source_section
            )
        )

    def handle_inlining(self, mgenc):
        if self._context_level == 0:
            from som.compiler.ast.variable import Local

            # we got inlined

            assert isinstance(
                self._var, Local
            ), "We are not currently inlining any blocks with arguments"
            self._var = mgenc.get_inlined_local(self._var, 0)
        else:
            self._context_level -= 1

    def handle_outer_inlined(self, removed_ctx_level, mgenc_with_inlined):
        if self._context_level > removed_ctx_level:
            self._context_level -= 1
        elif self._context_level == removed_ctx_level:
            from som.compiler.ast.variable import Local

            # locals have been inlined into the outer context already
            # so, we need to look up the right one and fix up the index
            # at this point, the lexical scope has not been changed
            # so, we should still be able to find the right one
            assert isinstance(
                self._var, Local
            ), "We are not currently inlining any blocks with arguments"
            self._var = mgenc_with_inlined.get_inlined_local(
                self._var, self._context_level
            )


class _NonLocalVariableNode(ContextualNode):
    _immutable_fields_ = ["_frame_idx"]

    def __init__(self, context_level, frame_idx, source_section):
        ContextualNode.__init__(self, context_level, source_section)
        assert frame_idx >= 0
        assert context_level > 0
        self._frame_idx = frame_idx


class NonLocalVariableReadNode(_NonLocalVariableNode):
    def execute(self, frame):
        block = self.determine_block(frame)
        assert isinstance(block, AstBlock)
        return block.get_from_outer(self._frame_idx)

    def handle_inlining(self, mgenc):
        self._context_level -= 1
        if self._context_level == 0:
            if self._frame_idx == FRAME_AND_INNER_RCVR_IDX:
                # this is the self access
                self.replace(
                    LocalFrameVarReadNode(self._frame_idx, self.source_section)
                )
            else:
                raise NotImplementedError("not yet implemented")

    def handle_outer_inlined(self, removed_ctx_level, mgenc_with_inlined):
        assert (
            self._context_level > removed_ctx_level
        ), "This is should really just be self reads"
        self._context_level -= 1
        assert (
            self._context_level > 0
        ), "This should remain true, because a block enclosing this one got inlined somewhere"


class NonLocalVariableWriteNode(_NonLocalVariableNode):
    _immutable_fields_ = ["_value_expr?"]
    _child_nodes_ = ["_value_expr"]

    def __init__(self, context_level, frame_idx, value_expr, source_section=None):
        _NonLocalVariableNode.__init__(self, context_level, frame_idx, source_section)
        self._value_expr = self.adopt_child(value_expr)

    def execute(self, frame):
        value = self._value_expr.execute(frame)
        self.determine_block(frame).set_outer(self._frame_idx, value)
        return value

    def write_value(self, frame, value):
        self.determine_block(frame).set_outer(self._frame_idx, value)


class _LocalVariableNode(ExpressionNode):
    _immutable_fields_ = ["_frame_idx"]

    def __init__(self, frame_idx, source_section):
        ExpressionNode.__init__(self, source_section)
        assert frame_idx >= 0
        self._frame_idx = frame_idx


class _LocalVariableWriteNode(_LocalVariableNode):
    _immutable_fields_ = ["_expr?"]
    _child_nodes_ = ["_expr"]

    def __init__(self, frame_idx, expr, source_section=None):
        _LocalVariableNode.__init__(self, frame_idx, source_section)
        self._expr = self.adopt_child(expr)


class LocalInnerVarReadNode(_LocalVariableNode):
    def execute(self, frame):
        return read_inner(frame, self._frame_idx)


class LocalInnerVarWriteNode(_LocalVariableWriteNode):
    def execute(self, frame):
        val = self._expr.execute(frame)
        write_inner(frame, self._frame_idx, val)
        return val

    def write_value(self, frame, value):
        write_inner(frame, self._frame_idx, value)


class LocalFrameVarReadNode(_LocalVariableNode):
    def execute(self, frame):
        return read_frame(frame, self._frame_idx)

    def is_self(self):
        return self._frame_idx == FRAME_AND_INNER_RCVR_IDX


class LocalFrameVarWriteNode(_LocalVariableWriteNode):
    def execute(self, frame):
        val = self._expr.execute(frame)
        write_frame(frame, self._frame_idx, val)
        return val

    def write_value(self, frame, value):
        write_frame(frame, self._frame_idx, value)
