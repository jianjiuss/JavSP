"""日志配置：控制台输出INFO及以上，文件记录DEBUG及以上的完整日志"""
import logging
import os
import sys

__all__ = ['ColoredFormatter', 'default_log_path', 'setup_logging']


class ColoredFormatter(logging.Formatter):
    """为不同level的日志着色"""
    NO_STYLE = '\033[0m'
    COLOR_MAP = {
        logging.DEBUG:    '\033[1;30m',  # grey
        logging.WARNING:  '\033[1;33m',  # light yellow
        logging.ERROR:    '\033[1;31m',  # light red
        logging.CRITICAL: '\033[0;31m',  # red
    }

    def format(self, record):
        raw = super().format(record)
        color = self.COLOR_MAP.get(record.levelno, self.NO_STYLE)
        return color + raw + self.NO_STYLE


# 记录本模块添加的handler，重复配置时先移除，避免重复输出
_handlers = []


def default_log_path() -> str:
    """默认的日志文件路径：打包后位于程序所在目录，从源码运行时位于当前目录"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.getcwd()
    return os.path.join(base, 'JavSP.log')


def setup_logging(log_file=None, console_level=logging.INFO, file_level=logging.DEBUG) -> str:
    """配置根logger，返回实际使用的日志文件路径

    Args:
        log_file (str, optional): 日志文件路径，留空时使用default_log_path()
        console_level: 输出到控制台的最低日志级别
        file_level: 写入日志文件的最低日志级别
    """
    # 延迟导入：javsp.print被导入时会接管内置print，避免仅导入本模块就改变print的行为
    from javsp.print import TqdmOut

    global _handlers
    root_logger = logging.getLogger()
    # 先移除之前由本模块添加的handler，避免重复输出
    for handler in _handlers:
        root_logger.removeHandler(handler)
        handler.close()
    _handlers = []
    root_logger.setLevel(logging.DEBUG)
    # 图片处理库的DEBUG日志过于琐碎，只保留WARNING及以上
    logging.getLogger('PIL').setLevel(logging.WARNING)

    # 使用TqdmOut作为输出流，避免日志输出与tqdm的进度条互相覆盖
    console_handler = logging.StreamHandler(stream=TqdmOut)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(ColoredFormatter(fmt='%(message)s'))
    root_logger.addHandler(console_handler)
    _handlers.append(console_handler)

    if log_file is None:
        log_file = default_log_path()
    try:
        file_handler = logging.FileHandler(filename=log_file, mode='a', encoding='utf-8')
    except OSError as e:
        logging.getLogger(__name__).warning(f'无法写入日志文件 {log_file}，本次运行仅输出到控制台: {e}')
    else:
        file_handler.setLevel(file_level)
        file_handler.setFormatter(logging.Formatter(
            fmt='%(asctime)s %(name)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        root_logger.addHandler(file_handler)
        _handlers.append(file_handler)

    return log_file
