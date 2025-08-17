from rlib.objectmodel import compute_identity_hash
from som.primitives.primitives import Primitives
from som.vm.current import current_universe

from som.vm.globals import trueObject, falseObject
from som.vmobjects.array import Array
from som.vmobjects.object_with_layout import Object
from som.vmobjects.primitive import UnaryPrimitive, BinaryPrimitive, TernaryPrimitive


def _equals(op1, op2):
    if op1 is op2:
        return trueObject
    return falseObject


def _object_size(rcvr):
    from som.vmobjects.integer import Integer

    size = 0

    if isinstance(rcvr, Object):
        size = rcvr.get_number_of_fields()
    elif isinstance(rcvr, Array):
        size = rcvr.get_number_of_indexable_fields()

    return Integer(size)


def _hashcode(rcvr):
    from som.vmobjects.integer import Integer

    return Integer(compute_identity_hash(rcvr))


def _inst_var_at(rcvr, idx):
    return rcvr.get_field(idx.get_embedded_integer() - 1)


def _inst_var_at_put(rcvr, idx, val):
    rcvr.set_field(idx.get_embedded_integer() - 1, val)
    return rcvr


def _inst_var_named(rcvr, arg):
    i = rcvr.get_field_index(arg)
    return rcvr.get_field(i)


def _halt(rcvr):
    # noop
    print("BREAKPOINT")
    return rcvr


def _class(rcvr):
    return rcvr.get_class(current_universe)


def _perform(rcvr, selector):
    invokable = rcvr.get_object_layout(current_universe).lookup_invokable(selector)
    return invokable.invoke_1(rcvr)


def _perform_in_superclass(rcvr, selector, clazz):
    invokable = clazz.lookup_invokable(selector)
    return invokable.invoke_1(rcvr)


def _perform_with_arguments(rcvr, selector, args):
    num_args = args.get_number_of_indexable_fields() + 1

    invokable = rcvr.get_object_layout(current_universe).lookup_invokable(selector)

    if num_args == 1:
        return invokable.invoke_1(rcvr)
    if num_args == 2:
        return invokable.invoke_2(rcvr, args.get_indexable_field(0))
    if num_args == 3:
        return invokable.invoke_3(
            rcvr, args.get_indexable_field(0), args.get_indexable_field(1)
        )
    raise Exception("Not yet implemented")


class ObjectPrimitivesBase(Primitives):
    def install_primitives(self):
        self._install_instance_primitive(BinaryPrimitive("==", _equals))
        self._install_instance_primitive(UnaryPrimitive("hashcode", _hashcode))
        self._install_instance_primitive(UnaryPrimitive("objectSize", _object_size))
        self._install_instance_primitive(BinaryPrimitive("instVarAt:", _inst_var_at))
        self._install_instance_primitive(
            TernaryPrimitive("instVarAt:put:", _inst_var_at_put)
        )
        self._install_instance_primitive(
            BinaryPrimitive("instVarNamed:", _inst_var_named)
        )

        self._install_instance_primitive(UnaryPrimitive("halt", _halt))
        self._install_instance_primitive(UnaryPrimitive("class", _class))

        self._install_instance_primitive(BinaryPrimitive("perform:", _perform))
        self._install_instance_primitive(
            TernaryPrimitive("perform:inSuperclass:", _perform_in_superclass)
        )
        self._install_instance_primitive(
            TernaryPrimitive("perform:withArguments:", _perform_with_arguments)
        )
