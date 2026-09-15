import contextlib
import sys
import threading

from javsp.config import Cfg


# 标记当前是否有线程正在等待用户输入，供超时相关的逻辑参考
_prompt_state_lock = threading.Lock()
_prompt_state_count = 0


@contextlib.contextmanager
def waiting_for_input():
    """标记进入/退出等待用户输入的状态"""
    global _prompt_state_count
    with _prompt_state_lock:
        _prompt_state_count += 1
    try:
        yield
    finally:
        with _prompt_state_lock:
            _prompt_state_count -= 1


def is_waiting_for_input() -> bool:
    """是否有线程正在等待用户输入"""
    with _prompt_state_lock:
        return _prompt_state_count > 0


def prompt(message: str, what: str) -> str:
    if Cfg().other.interactive:
        with waiting_for_input():
            return input(message)
    else:
        print(f"缺少{what}")
        sys.exit(1)
