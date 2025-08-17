import math

INFINITY = 1e200 * 1e200

try:
    from rpython.rlib.rfloat import formatd, DTSF_ADD_DOT_0
    from rpython.rlib.rfloat import round_double  # pylint: disable=unused-import

    def float_to_str(value):
        s = formatd(value, "f", 14, DTSF_ADD_DOT_0)
        s = s.rstrip('0')
        if s.endswith('.'):
            s += '0'
        return s

except ImportError:
    "NOT_RPYTHON"

    def float_to_str(value):
        s = "%.14f" % value
        s = s.rstrip('0')
        if s.endswith('.'):
            s += '0'
        return s

    def round_double(value, _ndigits):
        # round() from libm, which is not available on all platforms!
        # This version rounds away from zero.
        abs_value = abs(value)
        rounded = math.floor(abs_value + 0.5)
        if rounded - abs_value < 1.0:
            return math.copysign(rounded, value)

        # 'abs_value' is just in the wrong range: its exponent is precisely
        # the one for which all integers are representable but not any
        # half-integer.  It means that 'abs_value + 0.5' computes equal to
        # 'abs_value + 1.0', which is not equal to 'abs_value'.  So 'rounded - abs_value'
        # computes equal to 1.0.  In this situation, we can't return
        # 'rounded' because 'abs_value' was already an integer but 'rounded' is the next
        # integer!  But just returning the original 'x' is fine.
        return value
