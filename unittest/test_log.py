import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import javsp.log as javsp_log
from javsp.log import setup_logging


def cleanup_logging():
    """移除setup_logging添加的handler，避免影响其他测试"""
    root_logger = logging.getLogger()
    for handler in list(javsp_log._handlers):
        root_logger.removeHandler(handler)
        handler.close()
    javsp_log._handlers.clear()
    root_logger.setLevel(logging.WARNING)


def test_setup_logging_writes_info_to_console_and_debug_to_file(tmp_path):
    log_file = tmp_path / 'JavSP.log'
    try:
        setup_logging(log_file=str(log_file))
        root_logger = logging.getLogger()
        console_handlers = [i for i in root_logger.handlers
                            if isinstance(i, logging.StreamHandler)
                            and not isinstance(i, logging.FileHandler)]
        file_handlers = [i for i in root_logger.handlers if isinstance(i, logging.FileHandler)]
        assert any(i.level == logging.INFO for i in console_handlers)
        assert any(i.level == logging.DEBUG for i in file_handlers)
        assert logging.getLogger('PIL').level == logging.WARNING

        logger = logging.getLogger('unittest.log')
        logger.debug('调试级别的日志')
        logger.info('信息级别的日志')
        for handler in root_logger.handlers:
            handler.flush()

        content = log_file.read_text(encoding='utf-8')
        assert '调试级别的日志' in content
        assert '信息级别的日志' in content
    finally:
        cleanup_logging()


def test_setup_logging_does_not_duplicate_handlers(tmp_path):
    try:
        setup_logging(log_file=str(tmp_path / 'first.log'))
        setup_logging(log_file=str(tmp_path / 'second.log'))

        handlers = javsp_log._handlers
        assert len(handlers) == 2
        assert len({id(i) for i in logging.getLogger().handlers}) == len(logging.getLogger().handlers)
    finally:
        cleanup_logging()
