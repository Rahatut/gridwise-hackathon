# conftest.py — makes the project root importable during pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
