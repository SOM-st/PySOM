from som.interpreter.ast.nodes.expression_node import ExpressionNode


class LiteralNode(ExpressionNode):
    _immutable_fields_ = ["_value"]

    def __init__(self, value, source_section):
        ExpressionNode.__init__(self, source_section)
        self._value = value

    def execute(self, _frame):
        return self._value

    def create_trivial_method(self, signature):
        from som.vmobjects.method_trivial import LiteralReturn

        return LiteralReturn(signature, self._value, self.source_section)
