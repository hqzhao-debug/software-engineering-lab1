#!/bin/zsh
set -u
task_dir="${0:A:h}"
code_dir="$task_dir"
cd "$code_dir" || exit 1

python_bin=""
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  printf '需要 Python 3.11 或更新版本。安装后请再次双击此文件。\n按回车关闭。'
  read -r reply
  exit 1
fi

printf '正在打开校园循物图形界面……\n'
printf '浏览器是操作界面；此 Terminal 窗口负责维持本地服务。\n'
printf '操作时请保持此窗口打开；结束时按 Control+C 停止服务。\n\n'
"$python_bin" -m campus_market.webapp --demo --data-dir "$code_dir/data/gui-demo" --port 0
status_code=$?
if [[ "$status_code" -ne 0 && "$status_code" -ne 130 ]]; then
  printf '\n启动失败（退出码 %s）。请保留上方错误信息。\n按回车关闭。' "$status_code"
  read -r reply
fi
exit "$status_code"
