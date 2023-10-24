from rlib.jit import JitDriver, we_are_jitted

from som.interpreter.ast.nodes.expression_node import ExpressionNode
from som.vm.globals import nilObject
from som.vmobjects.double import Double
from som.vmobjects.integer import Integer


def get_printable_location(self):
    assert isinstance(self, ToDoInlined)
    source = self.source_section
    return "#to:do: %s:%d:%d" % (
        source.file,
        source.coord.start_line,
        source.coord.start_column,
    )


driver_int = JitDriver(
    greens=["self"],
    reds="auto",
    is_recursive=True,
    get_printable_location=get_printable_location,
)

driver_double = JitDriver(
    greens=["self"],
    reds="auto",
    is_recursive=True,
    get_printable_location=get_printable_location,
)


class ToDoInlined(ExpressionNode):
    _immutable_fields_ = [
        "_from_expr?",
        "_to_expr?",
        "_do_expr?",
        "_idx_var",
        "_idx_write?",
    ]
    _child_nodes_ = ["_from_expr", "_to_expr", "_do_expr", "_idx_write"]

    def __init__(self, from_expr, to_expr, do_expr, idx_var, source_section):
        ExpressionNode.__init__(self, source_section)
        self._from_expr = self.adopt_child(from_expr)
        self._to_expr = self.adopt_child(to_expr)
        self._do_expr = self.adopt_child(do_expr)
        self._idx_var = idx_var
        self._idx_write = self.adopt_child(idx_var.get_write_node(0, None))

    def execute(self, frame):
        start = self._from_expr.execute(frame)
        end = self._to_expr.execute(frame)

        if isinstance(start, Double):
            return self._execute_double(frame, start, end)

        assert isinstance(start, Integer)

        if isinstance(end, Integer):
            end_int = end.get_embedded_integer()
        else:
            assert isinstance(end, Double)
            end_int = int(end.get_embedded_double())

        if we_are_jitted():
            self._idx_write.write_value(frame, nilObject)

        i = start.get_embedded_integer()
        while i <= end_int:
            driver_int.jit_merge_point(self=self)
            self._idx_write.write_value(frame, Integer(i))
            self._do_expr.execute(frame)
            if we_are_jitted():
                self._idx_write.write_value(frame, nilObject)
            i += 1

        return start

    def _execute_double(self, frame, start, end):
        if isinstance(end, Integer):
            end_d = float(end.get_embedded_integer())
        else:
            assert isinstance(end, Double)
            end_d = end.get_embedded_double()

        if we_are_jitted():
            self._idx_write.write_value(frame, nilObject)

        i = start.get_embedded_double()
        while i <= end_d:
            driver_double.jit_merge_point(self=self)
            self._idx_write.write_value(frame, Double(i))
            self._do_expr.execute(frame)
            if we_are_jitted():
                self._idx_write.write_value(frame, nilObject)
            i += 1.0

        return start
