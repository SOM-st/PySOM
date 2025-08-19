import time

from rlib import rgc, jit
from rlib.streamio import open_file_as_stream, readall_from_stream

from som.primitives.primitives import Primitives
from som.vm.current import current_universe
from som.vm.globals import nilObject, trueObject, falseObject
from som.vm.universe import std_print, std_println, error_print, error_println
from som.vmobjects.primitive import UnaryPrimitive, BinaryPrimitive, TernaryPrimitive


def _load(_rcvr, arg):
    result = current_universe.load_class(arg)
    return result if result else nilObject


def _exit(_rcvr, error):
    return current_universe.exit(error.get_embedded_integer())


def _global(_rcvr, argument):
    result = current_universe.get_global(argument)
    return result if result else nilObject


def _has_global(_rcvr, arg):
    if current_universe.has_global(arg):
        return trueObject
    return falseObject


def _global_put(rcvr, argument, value):
    current_universe.set_global(argument, value)
    return rcvr


def _print_string(rcvr, argument):
    std_print(argument.get_embedded_string())
    return rcvr


def _print_newline(rcvr):
    std_println()
    return rcvr


def _error_print(rcvr, string):
    error_print(string.get_embedded_string())
    return rcvr


def _error_println(rcvr, string):
    error_println(string.get_embedded_string())
    return rcvr


def _time(_rcvr):
    from som.vmobjects.integer import Integer

    since_start = time.time() - current_universe.start_time
    return Integer(int(since_start * 1000))


def _ticks(_rcvr):
    from som.vmobjects.integer import Integer

    since_start = time.time() - current_universe.start_time
    return Integer(int(since_start * 1000000))


@jit.dont_look_inside
def _load_file(_rcvr, file_name):
    try:
        input_file = open_file_as_stream(file_name.get_embedded_string(), "r")
        try:
            result = readall_from_stream(input_file)
            from som.vmobjects.string import String

            return String(result)
        finally:
            input_file.close()
    except (OSError, IOError):
        pass
    return nilObject


@jit.dont_look_inside
def _full_gc(_rcvr):
    rgc.collect()
    return trueObject


class SystemPrimitivesBase(Primitives):
    def install_primitives(self):
        self._install_instance_primitive(BinaryPrimitive("load:", _load))
        self._install_instance_primitive(BinaryPrimitive("exit:", _exit))
        self._install_instance_primitive(BinaryPrimitive("hasGlobal:", _has_global))
        self._install_instance_primitive(BinaryPrimitive("global:", _global))
        self._install_instance_primitive(TernaryPrimitive("global:put:", _global_put))
        self._install_instance_primitive(BinaryPrimitive("printString:", _print_string))
        self._install_instance_primitive(UnaryPrimitive("printNewline", _print_newline))
        self._install_instance_primitive(BinaryPrimitive("errorPrint:", _error_print))
        self._install_instance_primitive(
            BinaryPrimitive("errorPrintln:", _error_println)
        )

        self._install_instance_primitive(UnaryPrimitive("time", _time))
        self._install_instance_primitive(UnaryPrimitive("ticks", _ticks))
        self._install_instance_primitive(UnaryPrimitive("fullGC", _full_gc))

        self._install_instance_primitive(BinaryPrimitive("loadFile:", _load_file))
