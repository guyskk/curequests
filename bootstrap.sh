#!/bin/bash
set -ex

pip install --upgrade setuptools
pip install -r requirements.txt
pip install -e .
pre-commit install
