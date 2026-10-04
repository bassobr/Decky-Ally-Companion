import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "py_modules"))
FIXTURES = os.path.join(HERE, "fixtures")
