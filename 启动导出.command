#!/bin/zsh
cd "${0:A:h}"
if command -v python3 >/dev/null 2>&1; then
  python3 live_export.py
else
  echo '需要先安装 Python 3：https://www.python.org/downloads/'
  read '?按回车关闭'
fi
