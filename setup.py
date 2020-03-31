from setuptools import setup, find_packages
import sys
import os.path

# Must be one line or PyPI will cut it off
DESC = ("A colormap tool")

LONG_DESC = open("README.rst").read()

setup(
    name="viscm",
    version="0.9.1",
    description=DESC,
    long_description=LONG_DESC,
    author="Nathaniel J. Smith, Stefan van der Walt",
    author_email="njs@pobox.com, stefanv@berkeley.edu",
    url="https://github.com/bids/viscm",
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
                      "matplotlib>=2.2.4",
                      "numpy>=1.8",
                      "pyqt5==5.12.*",
                      "scipy>=1.0.0"],
    python_requires='>=3.5, <4',
    package_data={'viscm': ['examples/*']},
    entry_points={
        'console_scripts': [
            "viscm = viscm.gui:main"]},
)
