import os
import sys
import random
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from javsp.func import * 


def test_remove_trail_actor_in_title():
    run = remove_trail_actor_in_title
    delimiters = list('-xX &·,;　＆・，；')
    title1 = '东风夜放花千树，更吹落、星如雨。'
    title2 = '辛弃疾 ' + title1
    names = ['辛弃疾', '牛顿', '爱因斯坦', '阿基米德', '伽利略']

    def combine(items):
        sep = random.choice(delimiters)
        new_str = sep.join(items)
        print(new_str)
        return new_str

    # 定义测试用例
    assert title1 == run(combine([title1, '辛弃疾']), names)
    assert title1 == run(combine([title1] + names), names)
    assert title1 == run(combine([title1, '辛弃疾']), names)
    assert title2 == run(combine([title2] + names), names)


def test_join_threads_times_out_without_interaction():
    th = threading.Thread(target=time.sleep, args=(0.5,))
    th.start()

    join_threads([th], 0.1, waiting_check=lambda: False, poll_interval=0.01)

    assert th.is_alive()
    th.join()


def test_join_threads_extends_timeout_while_waiting_input():
    th = threading.Thread(target=time.sleep, args=(0.5,))
    th.start()

    join_threads([th], 0.1, waiting_check=lambda: True, poll_interval=0.01)

    assert not th.is_alive()
