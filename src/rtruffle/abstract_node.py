from rlib.unroll import unrolling_iterable


class AbstractNode(object):
    pass


def _get_all_child_fields(clazz):
    cls = clazz
    field_names = []
    while cls is not AbstractNode:
        if hasattr(cls, "_child_nodes_"):
            field_names += cls._child_nodes_  # pylint: disable=protected-access
        cls = cls.__base__

    return set(field_names)


def _generate_replace_method(cls):
    child_fields = unrolling_iterable(_get_all_child_fields(cls))

    def _replace_child_with(parent_node, old_child, new_child):
        was_replaced = False  # pylint: disable=unused-variable
        for child_slot in child_fields:
            if child_slot.endswith("[*]"):
                slot_name = child_slot[:-3]
                nodes = getattr(parent_node, slot_name)
                if nodes and old_child in nodes:
                    # update old list, because iterators might have a copy of it
                    for i, n in enumerate(nodes):
                        if n is old_child:
                            nodes[i] = new_child
                    setattr(
                        parent_node, slot_name, nodes[:]
                    )  # TODO: figure out whether we need the copy of the list here
                    was_replaced = True
            else:
                current = getattr(parent_node, child_slot)
                if current is old_child:
                    setattr(parent_node, child_slot, new_child)
                    was_replaced = True
        # TODO: method recursion is a problem causing specialization more than
        #       once of a node if the containing method is already on the stack
        # if not was_replaced:
        #     raise ValueError("%s was not a direct child node of %s" % (
        #         old_child, parent_node))
        return new_child

    cls.replace_child_with = _replace_child_with


def _generate_adapt_after_inlining(cls):
    child_fields = unrolling_iterable(_get_all_child_fields(cls))

    def _adapt_after_inlining(node, mgenc):
        for child_slot in child_fields:
            if child_slot.endswith("[*]"):
                slot_name = child_slot[:-3]
                nodes = getattr(node, slot_name)
                if nodes:
                    for n in nodes:
                        n.adapt_after_inlining(mgenc)
            else:
                current = getattr(node, child_slot)
                if current is not None:
                    current.adapt_after_inlining(mgenc)
        node.handle_inlining(mgenc)

    cls.adapt_after_inlining = _adapt_after_inlining


def _generate_adapt_after_outer_inlined(cls):
    child_fields = unrolling_iterable(_get_all_child_fields(cls))

    def _adapt_after_outer_inlined(node, removed_ctx_level, mgenc_with_inlined):
        for child_slot in child_fields:
            if child_slot.endswith("[*]"):
                slot_name = child_slot[:-3]
                nodes = getattr(node, slot_name)
                if nodes:
                    for n in nodes:
                        n.adapt_after_outer_inlined(
                            removed_ctx_level, mgenc_with_inlined
                        )
            else:
                current = getattr(node, child_slot)
                if current is not None:
                    current.adapt_after_outer_inlined(
                        removed_ctx_level, mgenc_with_inlined
                    )
        node.handle_outer_inlined(removed_ctx_level, mgenc_with_inlined)

    cls.adapt_after_outer_inlined = _adapt_after_outer_inlined


class NodeInitializeMetaClass(type):
    def __init__(cls, name, bases, dic):
        type.__init__(cls, name, bases, dic)
        cls._initialize_node_class()  # pylint: disable=no-value-for-parameter

    def _initialize_node_class(cls):
        _generate_replace_method(cls)
        _generate_adapt_after_inlining(cls)
        _generate_adapt_after_outer_inlined(cls)
