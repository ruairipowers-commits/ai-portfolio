from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

ext = [
    Pybind11Extension(
        "qlbt_core",
        ["cpp/qlbt_core.cpp"],
        cxx_std=17,
        extra_compile_args=["-O3", "-pthread"],
        extra_link_args=["-pthread"],
    )
]

setup(
    name="qlbt",
    version="0.1.0",
    description="Event-driven tick backtester (Python) with C++ kernels",
    packages=["qlbt"],
    ext_modules=ext,
    cmdclass={"build_ext": build_ext},
    install_requires=["numpy", "pandas"],
    python_requires=">=3.9",
)
