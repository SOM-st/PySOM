from som.interpreter.ast.frame import FRAME_AND_INNER_RCVR_IDX
from som.interpreter.ast.nodes.variable_node import (
    UninitializedReadNode,
    UninitializedWriteNode,
    NonLocalVariableReadNode,
    LocalInnerVarReadNode,
    LocalFrameVarReadNode,
    NonLocalVariableWriteNode,
    LocalInnerVarWriteNode,
    LocalFrameVarWriteNode,
)
from som.interpreter.bc.bytecodes import Bytecodes


class _Variable(object):
    _immutable_fields_ = ["idx", "access_idx", "source"]

    def __init__(self, name, idx, source):
        self.source = source
        self._name = name
        self._is_accessed = False
        self._is_accessed_out_of_context = False
        self.access_idx = -1
        self.idx = idx
        assert idx >= 0

    def set_access_index(self, value):
        assert value >= 0
        self.access_idx = value

    def is_accessed(self):
        return self._is_accessed

    def is_accessed_out_of_context(self):
        return self._is_accessed_out_of_context

    def mark_accessed(self, context_level):
        self._is_accessed = True
        if context_level > 0:
            self._is_accessed_out_of_context = True

    def get_read_node(self, context_level):
        self.mark_accessed(context_level)
        return UninitializedReadNode(self, context_level, None)

    def get_write_node(self, context_level, value_expr):
        self.mark_accessed(context_level)
        return UninitializedWriteNode(self, context_level, value_expr, None)

    def get_initialized_read_node(self, context_level, source_section):
        assert self.access_idx >= 0
        if context_level > 0:
            return NonLocalVariableReadNode(
                context_level, self.access_idx, source_section
            )
        if self.is_accessed_out_of_context():
            return LocalInnerVarReadNode(self.access_idx, source_section)
        return LocalFrameVarReadNode(self.access_idx, source_section)

    def get_initialized_write_node(self, context_level, value_expr, source_section):
        assert self.access_idx >= 0
        if context_level > 0:
            return NonLocalVariableWriteNode(
                context_level, self.access_idx, value_expr, source_section
            )
        if self.is_accessed_out_of_context():
            return LocalInnerVarWriteNode(self.access_idx, value_expr, source_section)
        return LocalFrameVarWriteNode(self.access_idx, value_expr, source_section)

    def get_push_bytecode(self, ctx_level):
        if self.is_accessed_out_of_context():
            if ctx_level == 0:
                if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 0:
                    return Bytecodes.push_inner_0
                if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 1:
                    return Bytecodes.push_inner_1
                if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 2:
                    return Bytecodes.push_inner_2
            return Bytecodes.push_inner

        if ctx_level == 0:
            if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 0:
                return Bytecodes.push_frame_0
            if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 1:
                return Bytecodes.push_frame_1
            if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 2:
                return Bytecodes.push_frame_2
        return Bytecodes.push_frame

    def get_pop_bytecode(self, ctx_level):
        if self.is_accessed_out_of_context():
            if ctx_level == 0:
                if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 0:
                    return Bytecodes.pop_inner_0
                if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 1:
                    return Bytecodes.pop_inner_1
                if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 2:
                    return Bytecodes.pop_inner_2
            return Bytecodes.pop_inner

        if ctx_level == 0:
            if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 0:
                return Bytecodes.pop_frame_0
            if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 1:
                return Bytecodes.pop_frame_1
            if self.access_idx == FRAME_AND_INNER_RCVR_IDX + 2:
                return Bytecodes.pop_frame_2
        return Bytecodes.pop_frame

    def get_qualified_name(self):
        return (
            self._name
            + ":"
            + str(self.source.coord.start_line)
            + ":"
            + str(self.source.coord.start_column)
        )


class Argument(_Variable):
    def __init__(self, name, idx, source):
        _Variable.__init__(self, name, idx, source)
        assert name == "self" or name == "$blockSelf" or idx >= 0

    def is_self(self):
        return self._name == "self"

    def get_read_node(self, context_level):
        if self._name == "self" or self._name == "$blockSelf":
            self.mark_accessed(context_level)
            if context_level > 0:
                return NonLocalVariableReadNode(
                    context_level, FRAME_AND_INNER_RCVR_IDX, None
                )
            return LocalFrameVarReadNode(FRAME_AND_INNER_RCVR_IDX, None)
        return _Variable.get_read_node(self, context_level)

    def get_initialized_read_node(self, context_level, source_section):
        if self._name == "self" or self._name == "$blockSelf":
            if context_level > 0:
                return NonLocalVariableReadNode(
                    context_level, FRAME_AND_INNER_RCVR_IDX, source_section
                )
            return LocalFrameVarReadNode(FRAME_AND_INNER_RCVR_IDX, source_section)
        return _Variable.get_initialized_read_node(self, context_level, source_section)

    def copy_for_inlining(self, idx):
        if self._name == "$blockSelf":
            return None
        assert self._name != "self"
        return Local(self._name, idx, self.source)

    def __str__(self):
        return "Argument(" + self._name + " idx: " + str(self.idx) + ")"


class Local(_Variable):
    def copy_for_inlining(self, idx):
        return Local(self._name, idx, self.source)

    def __str__(self):
        return "Local(" + self._name + " idx: " + str(self.idx) + ")"
