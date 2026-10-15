#!/usr/bin/env bash
# Build the Lambda deployment package: backend/build/lambda.zip
# Dependencies are fetched as Linux x86_64 wheels for Python 3.13, so this works
# from any machine that has pip (CI runs it on every deploy).
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf build/lambda build/lambda.zip
mkdir -p build/lambda
python -m pip install --quiet --target build/lambda \
    --platform manylinux2014_x86_64 --implementation cp --python-version 3.13 \
    --only-binary=:all: -r requirements-lambda.txt
cp -r app build/lambda/app
find build/lambda -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd build/lambda && python -c "import shutil; shutil.make_archive('../lambda', 'zip', '.')")
echo "built build/lambda.zip ($(du -h build/lambda.zip | cut -f1))"
