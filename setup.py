from setuptools import setup, find_packages
import sys
import os.path

# Must be one line or PyPI will cut it off
DESC = ("A colormap tool")

LONG_DESC = open("README.rst").read()

setup(
    name="viscm",
    version="0.10.0",
    description=DESC,
    long_description=LONG_DESC,
    author="Nathaniel J. Smith, Stefan van der Walt, Ellert van der Velden",
    author_email="njs@pobox.com, stefanv@berkeley.edu, ellert_vandervelden@outlook.com",
    url="https://github.com/1313e/viscm",
    license="MIT",
    classifiers =
      [ "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        ],
    packages=find_packages(),
    install_requires=["colorspacious>=1.1.0",
                      "matplotlib>=3.2.0",
                      "numpy>=1.8",
                      "pyqt5==5.12.*",
                      "scipy>=1.0.0",
                      "cmasher>=1.5.0"],
    python_requires='>=3.5, <4',
    package_data={'viscm': ['examples/*']},
    entry_points={
        'console_scripts': [
            "viscm = viscm.gui:main"]},
)
