import sys
import os
sys.path.insert(0, ".")
from legacy.assistant import process_input

print("HI:", repr(process_input("hi", user_id=1)))
print("HELLO:", repr(process_input("hello", user_id=1)))
print("MULTI:", repr(process_input("what is the time and what is 10 plus 15", user_id=1)))

