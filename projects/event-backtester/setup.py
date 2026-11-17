"""Builds the C++ kernel (event_backtester._core). Everything else is in pyproject.toml."""
from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

setup(
    ext_modules=[Pybind11Extension("event_backtester._core", ["cpp/core.cpp"], cxx_std=17,
                                   extra_compile_args=["-O3", "-pthread"], extra_link_args=["-pthread"])],
    cmdclass={"build_ext": build_ext},
)
