from rlib import jit
from som.vmobjects.abstract_object import AbstractObject


class AbstractMethod(AbstractObject):
    _immutable_fields_ = [
        "_signature",
        "_holder",
        "_lexical_scope",
    ]

    def __init__(self, signature, lexical_scope):
        AbstractObject.__init__(self)
        self._signature = signature
        self._holder = None
        self._lexical_scope = lexical_scope

    @staticmethod
    def is_primitive():
        return False

    @staticmethod
    def is_invokable():
        """We use this method to identify methods and primitives"""
        return True

    def get_argument(self, idx, ctx_level):
        return self._lexical_scope.get_argument(idx, ctx_level)

    def get_holder(self):
        return self._holder

    # XXX this means that the JIT doesn't see changes to the method object
    @jit.elidable_promote("all")
    def get_signature(self):
        return self._signature

    def get_class(self, universe):
        return universe.method_class

    def get_object_layout(self, universe):
        return universe.method_layout

    def __str__(self):
        if self._holder:
            holder = self._holder.get_name().get_embedded_string()
        else:
            holder = "nil"
        return "Method(" + holder + ">>" + str(self._signature) + ")"

    def merge_point_string(self):
        """debug info for the jit"""
        if self._holder:
            holder = self._holder.get_name().get_embedded_string()
        else:
            holder = "nil"
        return holder + ">>" + self._signature.get_embedded_string()
