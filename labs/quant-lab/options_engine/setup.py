from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

setup(
    name="optlib",
    version="0.1.0",
    description="Options pricing & Greeks engine: Black-Scholes, binomial trees, multithreaded Monte Carlo",
    ext_modules=[Pybind11Extension("optlib", ["cpp/optlib.cpp"], cxx_std=17,
                                   extra_compile_args=["-O3", "-pthread"], extra_link_args=["-pthread"])],
    cmdclass={"build_ext": build_ext},
    python_requires=">=3.9",
)
