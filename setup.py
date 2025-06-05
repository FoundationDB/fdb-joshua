"""
    joshua
"""
from distutils.core import setup, Extension
from collections import namedtuple

import os

childsubreaper = Extension("childsubreaper", ["childsubreaper/childsubreaper.c"])

Module = namedtuple(
    "Module",
    ["name", "desc", "requirements", "private_repos", "ext_modules", "platforms"],
)

all_modules = [
    Module(
        "joshua-client",
        "Joshua Client - interface to a great big supercomputer",
        ["argparse", "foundationdb==7.1.57", "python-dateutil", "lxml"],
        [],
        [childsubreaper],
        [
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: POSIX :: Linux",
        ],
    ),
    Module(
        "joshua",
        "Joshua - a supercomputer that runs simulations of war^H^H^Hdatabases",
        ["argparse", "foundationdb==7.1.57", "subprocess32"],
        [],
        [childsubreaper],
        ["Operating System :: POSIX :: Linux"],
    ),
]

if "ARTIFACT" in os.environ:
    if os.environ["ARTIFACT"] == "client":
        modules = [all_modules[0]]
    elif os.environ["ARTIFACT"] == "server":
        modules = [all_modules[1]]
    elif os.environ["ARTIFACT"] == "all":
        modules = all_modules
    else:
        raise ValueError(f"Unknown artifact: {os.environ['ARTIFACT']}")
else:
    modules = all_modules

for module in modules:
    setup(
        name=module.name,
        version="1.8.0",
        author="The FoundationDB Team",
        author_email="fdbteam@apple.com",
        url="https://www.foundationdb.org",
        description=module.desc,
        long_description="How about a nice game of chess?",
        packages=["joshua"],
        package_data={"joshua": ["joshua/*.py"]},
        install_requires=module.requirements,
        dependency_links=module.private_repos,
        ext_modules=module.ext_modules,
        classifiers=[
            "Development Status :: 5 - Production/Stable",
            "Intended Audience :: Developers",
            "License :: OSI Approved :: MIT License",
        ]
        + module.platforms
        + [
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: Implementation :: CPython",
        ],
    )
