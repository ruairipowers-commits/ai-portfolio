"""Builds the C++ engine (options_greeks_engine._optlib). Everything else is in pyproject.toml."""
from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

setup(
    ext_modules=[Pybind11Extension("options_greeks_engine._optlib", ["cpp/optlib.cpp"], cxx_std=17,
                                   extra_compile_args=["-O3", "-pthread"], extra_link_args=["-pthread"])],
    cmdclass={"build_ext": build_ext},
)
