from __future__ import absolute_import

from som.vmobjects.array import Array

class Method(Array):
    
    # Static field indices and number of method fields
    SIGNATURE_INDEX                 = Array.NUMBER_OF_OBJECT_FIELDS
    HOLDER_INDEX                    = 1 + SIGNATURE_INDEX
    NUMBER_OF_METHOD_FIELDS         = 1 + HOLDER_INDEX

    
    def __init__(self, nilObject, num_literals, num_locals, max_stack_elements,
                 num_bytecodes, signature):
        Array.__init__(self, nilObject, num_literals)
        
        self._receiver_class_table   = []
        self._invoked_methods        = []
        self._receiver_class_index   = 0

        self._invocation_count       = 0


        # Set the number of bytecodes in this method
        self._bytecodes              = ["\x00"] * num_bytecodes
        self._inline_cache_class     = [None]   * num_bytecodes
        self._inline_cache_invokable = [None]   * num_bytecodes
        
        self._number_of_locals       = num_locals
        self._maximum_number_of_stack_elements = max_stack_elements
        self._set_signature(signature)
        
    
    def is_primitive(self):
        return False
    
    def is_invokable(self):
        """In the RPython version, we use this method to identify methods 
           and primitives
        """
        return True
  
    def get_number_of_locals(self):
        # Get the number of locals (converted to a Java integer)
        return self._number_of_locals

    def get_maximum_number_of_stack_elements(self):
        # Get the maximum number of stack elements
        return self._maximum_number_of_stack_elements

    def get_signature(self):
        # Get the signature of this method by reading the field with signature
        # index
        return self.get_field(self.SIGNATURE_INDEX)

    def _set_signature(self, value):
        # Set the signature of this method by writing to the field with
        # signature index
        self.set_field(self.SIGNATURE_INDEX, value)

    def get_holder(self):
        # Get the holder of this method by reading the field with holder index
        return self.get_field(self.HOLDER_INDEX)

    def set_holder(self, value):
        # Set the holder of this method by writing to the field with holder index
        self.set_field(self.HOLDER_INDEX, value)

        # Make sure all nested invokables have the same holder
        for i in range(0, self.get_number_of_indexable_fields()):
            if self.get_indexable_field(i).is_invokable():
                self.get_indexable_field(i).set_holder(value)

    def get_constant(self, bytecode_index):
        # Get the constant associated to a given bytecode index
        return self.get_indexable_field(self.get_bytecode(bytecode_index + 1))

    def get_number_of_arguments(self):
        # Get the number of arguments of this method
        return self.get_signature().get_number_of_signature_arguments()
  
    def _get_default_number_of_fields(self):
        # Return the default number of fields in a method
        return self.NUMBER_OF_METHOD_FIELDS
  
    def get_number_of_bytecodes(self):
        # Get the number of bytecodes in this method
        return len(self._bytecodes)

    def get_bytecode(self, index):
        # Get the bytecode at the given index
        return ord(self._bytecodes[index])

    def set_bytecode(self, index, value):
        # Set the bytecode at the given index to the given value
        assert 0 <= value and value <= 255
        self._bytecodes[index] = chr(value)

    # TODO: remove these things
    def increase_invocation_counter(self):
        self._invocation_count += 1

    # TODO: remove these things
    def get_invocation_count(self):
        return self._invocation_count

    def invoke(self, frame, interpreter):
        # Increase the invocation counter
        self._invocation_count += 1
    
        # Allocate and push a new frame on the interpreter stack
        new_frame = interpreter.push_new_frame(self,
                                    interpreter.get_universe().nilObject)
        new_frame.copy_arguments_from(frame)

    # TODO: remove these things
    def get_receiver_class(self, index):
        return self._receiver_class_table[index]

    # TODO: remove these things
    def get_invoked_method(self, index):
        # return the last invoked method for a particular send
        return self._invoked_methods[index]

    # TODO: remove these things
    def add_receiver_class_and_method(self, rcvr_class, invokable):
        self._receiver_class_table.append(self._receiver_class_index, rcvr_class)
        self._invoked_methods.append(self._receiver_class_index, invokable)
        self._receiver_class_index += 1

        return self._receiver_class_index - 1

    # TODO: remove these things
    def is_receiver_class_table_full(self):
        return self._receiver_class_index == 255

    def __str__(self):
        return "Method(" + self.get_holder().get_name().get_string() + ">>" + str(self.get_signature()) + ")"

    def get_inline_cache_class(self, bytecode_index):
        return self._inline_cache_class[bytecode_index]

    def get_inline_cache_invokable(self, bytecode_index):
        return self._inline_cache_invokable[bytecode_index]

    def set_inline_cache(self, bytecode_index, receiver_class, invokable):
        self._inline_cache_class[bytecode_index]    = receiver_class
        self._inline_cache_invokable[bytecode_index] = invokable

    def merge_point_string(self):
        """ debug info for the jit """
        return "%s>>%s" % (self.get_holder().get_name().get_string(),
                           self.get_signature().get_string())
