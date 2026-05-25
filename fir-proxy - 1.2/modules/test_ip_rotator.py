# modules/test_ip_rotator.py

import unittest
import sys
import os
import threading
import time
import queue
import json
import tempfile
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ip_rotator import (
    RequestStatus, LogLevel, RequestRecord, RotationLogger,
    ProxyPoolManager, HealthMonitor, RequestScheduler, IPRotationManager
)


class TestRequestRecord(unittest.TestCase):
    def test_to_dict_success(self):
        record = RequestRecord(
            timestamp="2024-01-01 12:00:00",
            target_url="https://example.com",
            proxy_address="1.1.1.1:8080",
            status_code=200,
            response_time=0.35,
            proxy_ip="1.1.1.1",
            status=RequestStatus.SUCCESS,
        )
        d = record.to_dict()
        self.assertEqual(d['status'], 'success')
        self.assertEqual(d['proxy_address'], '1.1.1.1:8080')
        self.assertEqual(d['status_code'], 200)
        self.assertFalse(d['used_proxy'])

    def test_to_dict_failure(self):
        record = RequestRecord(
            timestamp="2024-01-01 12:00:00",
            target_url="https://example.com",
            proxy_address="1.1.1.1:8080",
            status_code=None,
            response_time=10.0,
            proxy_ip="1.1.1.1",
            status=RequestStatus.TIMEOUT,
            failure_reason="请求超时",
        )
        d = record.to_dict()
        self.assertEqual(d['status'], 'timeout')
        self.assertEqual(d['failure_reason'], '请求超时')

    def test_to_log_string(self):
        record = RequestRecord(
            timestamp="2024-01-01 12:00:00",
            target_url="https://example.com",
            proxy_address="1.1.1.1:8080",
            status_code=200,
            response_time=0.35,
            proxy_ip="1.1.1.1",
            status=RequestStatus.SUCCESS,
        )
        log_str = record.to_log_string()
        self.assertIn("[OK]", log_str)
        self.assertIn("1.1.1.1:8080", log_str)

    def test_to_log_string_with_failure(self):
        record = RequestRecord(
            timestamp="2024-01-01 12:00:00",
            target_url="https://example.com",
            proxy_address="1.1.1.1:8080",
            status_code=None,
            response_time=10.0,
            proxy_ip="1.1.1.1",
            status=RequestStatus.TIMEOUT,
            failure_reason="请求超时",
        )
        log_str = record.to_log_string()
        self.assertIn("[TIMEOUT]", log_str)
        self.assertIn("原因=请求超时", log_str)


class TestRotationLogger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.logger = RotationLogger(log_file=self.log_file, max_memory_records=100)

    def tearDown(self):
        try:
            os.remove(self.log_file)
        except OSError:
            pass
        try:
            os.rmdir(self.temp_dir)
        except OSError:
            pass

    def test_log_stores_records(self):
        self.logger.log("测试消息", LogLevel.INFO)
        records = self.logger.get_recent_records(10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['message'], "测试消息")
        self.assertEqual(records[0]['level'], "INFO")

    def test_log_max_memory_records(self):
        small_logger = RotationLogger(log_file=self.log_file, max_memory_records=5)
        for i in range(10):
            small_logger.log(f"消息 {i}")
        records = small_logger.get_recent_records(100)
        self.assertEqual(len(records), 5)

    def test_log_request(self):
        record = RequestRecord(
            timestamp="2024-01-01 12:00:00",
            target_url="https://example.com",
            proxy_address="1.1.1.1:8080",
            status_code=200,
            response_time=0.35,
            proxy_ip="1.1.1.1",
            status=RequestStatus.SUCCESS,
        )
        self.logger.log_request(record)
        records = self.logger.get_recent_records(10)
        self.assertEqual(len(records), 1)
        self.assertIn('detail', records[0])

    def test_log_with_external_queue(self):
        log_q = queue.Queue()
        self.logger.set_external_log_queue(log_q)
        self.logger.log("队列测试")
        msg = log_q.get_nowait()
        self.assertIn("队列测试", msg)

    def test_get_statistics(self):
        record_ok = RequestRecord(
            timestamp="2024-01-01", target_url="http://test.com",
            proxy_address="1.1.1.1:80", status_code=200,
            response_time=0.1, proxy_ip="1.1.1.1", status=RequestStatus.SUCCESS
        )
        record_fail = RequestRecord(
            timestamp="2024-01-01", target_url="http://test.com",
            proxy_address="2.2.2.2:80", status_code=None,
            response_time=10.0, proxy_ip="2.2.2.2", status=RequestStatus.TIMEOUT,
            failure_reason="timeout"
        )
        self.logger.log_request(record_ok)
        self.logger.log_request(record_fail)
        stats = self.logger.get_statistics()
        self.assertEqual(stats['total_requests'], 2)
        self.assertEqual(stats['successful'], 1)
        self.assertEqual(stats['failed'], 1)

    def test_export_log(self):
        self.logger.log("导出测试")
        export_path = os.path.join(self.temp_dir, "export.json")
        result = self.logger.export_log(export_path)
        self.assertTrue(result)
        with open(export_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_file_created(self):
        self.logger.log("文件测试")
        self.assertTrue(os.path.exists(self.log_file))


class MockRotator:
    def __init__(self, proxies=None):
        self._proxies = proxies or []
        self._current = None
        self._lock = threading.Lock()

    def get_active_proxies_count(self):
        return len([p for p in self._proxies if p.get('status') == 'Working'])

    def get_next_proxy(self):
        working = [p for p in self._proxies if p.get('status') == 'Working']
        if not working:
            return None
        for p in working:
            if p != self._current:
                self._current = p
                return p
        self._current = working[0]
        return working[0]

    def get_current_proxy(self):
        if self._current and self._current.get('status') == 'Working':
            return self._current
        return self.get_next_proxy()

    def get_proxy_by_address(self, addr):
        for p in self._proxies:
            if p.get('proxy') == addr:
                return p
        return None

    def update_proxy(self, addr, data):
        for p in self._proxies:
            if p.get('proxy') == addr:
                p.update(data)
                return True
        return False

    def report_failure(self, addr):
        for p in self._proxies:
            if p.get('proxy') == addr:
                p['status'] = 'Unavailable'

    def set_current_proxy_by_address(self, addr):
        for p in self._proxies:
            if p.get('proxy') == addr and p.get('status') == 'Working':
                self._current = p
                return p
        return None


class TestProxyPoolManager(unittest.TestCase):
    def setUp(self):
        self.proxies = [
            {'proxy': '1.1.1.1:8080', 'protocol': 'http', 'status': 'Working', 'score': 80, 'location': '中国'},
            {'proxy': '2.2.2.2:8080', 'protocol': 'socks5', 'status': 'Working', 'score': 60, 'location': '美国'},
            {'proxy': '3.3.3.3:8080', 'protocol': 'http', 'status': 'Unavailable', 'score': 10, 'location': '日本'},
        ]
        self.rotator = MockRotator(self.proxies)
        self.logger = RotationLogger(log_file=os.path.join(tempfile.mkdtemp(), "test_pm.log"))
        self.pool = ProxyPoolManager(self.rotator, self.logger)

    def test_get_current_proxy_initial(self):
        proxy = self.pool.get_current_proxy()
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy['status'], 'Working')

    def test_report_success(self):
        self.pool.report_success('1.1.1.1:8080', 0.5)
        proxy = self.rotator.get_proxy_by_address('1.1.1.1:8080')
        self.assertEqual(proxy['consecutive_failures'], 0)

    def test_report_failure_adds_to_blacklist(self):
        self.pool.report_failure('1.1.1.1:8080', 'timeout')
        status = self.pool.get_pool_status()
        self.assertGreater(status['blacklisted'], 0)

    def test_force_switch(self):
        first = self.pool.get_current_proxy()
        initial_switches = self.pool.get_pool_status()['total_switches']
        new_proxy = self.pool.force_switch("test switch")
        self.assertIsNotNone(new_proxy)
        self.assertEqual(self.pool.get_pool_status()['total_switches'], initial_switches + 1)

    def test_get_pool_status(self):
        self.pool.get_current_proxy()
        status = self.pool.get_pool_status()
        self.assertIn('active_proxies', status)
        self.assertIn('current_proxy', status)
        self.assertIn('total_switches', status)

    def test_cleanup_blacklist(self):
        self.pool.report_failure('1.1.1.1:8080', 'test')
        self.pool._blacklist['1.1.1.1:8080'] = time.time() - 1
        cleaned = self.pool.cleanup_blacklist()
        self.assertEqual(cleaned, 1)


class TestHealthMonitor(unittest.TestCase):
    def setUp(self):
        self.logger = RotationLogger(log_file=os.path.join(tempfile.mkdtemp(), "test_hm.log"))
        self.monitor = HealthMonitor(self.logger, failure_threshold=3, degradation_after_failures=5)

    def test_record_success_resets_failures(self):
        self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.monitor.record_success()
        status = self.monitor.get_health_status()
        self.assertEqual(status['consecutive_failures'], 0)

    def test_should_switch_after_threshold(self):
        for _ in range(3):
            self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.assertTrue(self.monitor.should_switch_proxy())

    def test_should_not_switch_below_threshold(self):
        for _ in range(2):
            self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.assertFalse(self.monitor.should_switch_proxy())

    def test_should_degrade(self):
        for _ in range(5):
            self.monitor.record_failure(RequestStatus.CONNECTION_ERROR)
        self.assertTrue(self.monitor.should_degrade())

    def test_switch_cooldown(self):
        for _ in range(3):
            self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.assertTrue(self.monitor.should_switch_proxy())
        self.assertFalse(self.monitor.should_switch_proxy())

    def test_domain_alert(self):
        for _ in range(10):
            self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.assertTrue(self.monitor.should_alert_domain())

    def test_domain_alert_resets_on_success(self):
        for _ in range(10):
            self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.monitor.record_success()
        self.assertFalse(self.monitor.should_alert_domain())

    def test_get_health_status(self):
        self.monitor.record_success()
        self.monitor.record_failure(RequestStatus.TIMEOUT)
        status = self.monitor.get_health_status()
        self.assertEqual(status['total_successes'], 1)
        self.assertEqual(status['total_failures'], 1)

    def test_reset(self):
        self.monitor.record_failure(RequestStatus.TIMEOUT)
        self.monitor.record_success()
        self.monitor.reset()
        status = self.monitor.get_health_status()
        self.assertEqual(status['consecutive_failures'], 0)
        self.assertEqual(status['total_failures'], 0)


class TestRequestScheduler(unittest.TestCase):
    def setUp(self):
        self.logger = RotationLogger(log_file=os.path.join(tempfile.mkdtemp(), "test_rs.log"))

    def test_init_values(self):
        scheduler = RequestScheduler("https://example.com", interval=0.5, timeout=10, logger=self.logger)
        self.assertEqual(scheduler.target_url, "https://example.com")
        self.assertEqual(scheduler.interval, 0.5)
        self.assertFalse(scheduler.is_running)

    def test_update_config(self):
        scheduler = RequestScheduler("https://example.com", interval=0.5, timeout=10)
        scheduler.update_config(target_url="https://new.com", interval=1.0)
        self.assertEqual(scheduler.target_url, "https://new.com")
        self.assertEqual(scheduler.interval, 1.0)

    @patch('ip_rotator.requests.Session')
    def test_execute_single_request_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_session_cls.return_value = mock_session

        scheduler = RequestScheduler("https://example.com", interval=0.5, timeout=10)
        scheduler._session = mock_session

        success_called = threading.Event()
        failure_called = threading.Event()

        def on_success(addr, resp_time):
            success_called.set()

        def on_failure(addr, status, reason):
            failure_called.set()

        proxy_info = {'proxy': '1.1.1.1:8080', 'protocol': 'http'}
        scheduler._execute_single_request(lambda: proxy_info, on_success, on_failure)
        self.assertTrue(success_called.is_set())
        self.assertFalse(failure_called.is_set())

    @patch('ip_rotator.requests.Session')
    def test_execute_single_request_timeout(self, mock_session_cls):
        import requests as real_requests
        mock_session = MagicMock()
        mock_session.get.side_effect = real_requests.exceptions.Timeout()
        mock_session_cls.return_value = mock_session

        scheduler = RequestScheduler("https://example.com", interval=0.5, timeout=10)
        scheduler._session = mock_session

        failure_called = threading.Event()
        failure_reason = [None]

        def on_failure(addr, status, reason):
            failure_called.set()
            failure_reason[0] = (addr, status, reason)

        proxy_info = {'proxy': '1.1.1.1:8080', 'protocol': 'http'}
        scheduler._execute_single_request(lambda: proxy_info, None, on_failure)
        self.assertTrue(failure_called.is_set())
        self.assertEqual(failure_reason[0][1], RequestStatus.TIMEOUT)

    def test_start_stop(self):
        scheduler = RequestScheduler("https://example.com", interval=10, timeout=5, logger=self.logger)
        mock_proxy = {'proxy': '1.1.1.1:8080', 'protocol': 'http'}

        with patch.object(scheduler, '_session', MagicMock()):
            scheduler.start(get_proxy_func=lambda: mock_proxy)
            self.assertTrue(scheduler.is_running)
            time.sleep(0.1)
            scheduler.stop()
            self.assertFalse(scheduler.is_running)

    def test_no_proxy_reports_degraded(self):
        scheduler = RequestScheduler("https://example.com", interval=0.5, timeout=10)
        scheduler._session = MagicMock()

        failure_called = threading.Event()
        failure_status = [None]

        def on_failure(addr, status, reason):
            failure_called.set()
            failure_status[0] = status

        scheduler._execute_single_request(lambda: None, None, on_failure)
        self.assertTrue(failure_called.is_set())
        self.assertEqual(failure_status[0], RequestStatus.DEGRADED)


class TestIPRotationManager(unittest.TestCase):
    def setUp(self):
        self.proxies = [
            {'proxy': '1.1.1.1:8080', 'protocol': 'http', 'status': 'Working', 'score': 80, 'location': '中国'},
            {'proxy': '2.2.2.2:1080', 'protocol': 'socks5', 'status': 'Working', 'score': 60, 'location': '美国'},
        ]
        self.rotator = MockRotator(self.proxies)
        self.log_q = queue.Queue()
        self.manager = IPRotationManager(self.rotator, self.log_q)

    def test_configure(self):
        self.manager.configure(target_url="https://test.com", request_interval=1.0)
        self.assertEqual(self.manager.config['target_url'], "https://test.com")
        self.assertEqual(self.manager.config['request_interval'], 1.0)

    def test_start_without_proxies(self):
        empty_rotator = MockRotator([])
        manager = IPRotationManager(empty_rotator, self.log_q)
        result = manager.start()
        self.assertFalse(result)

    def test_start_and_stop(self):
        result = self.manager.start()
        self.assertTrue(result)
        self.assertTrue(self.manager.is_running)
        time.sleep(0.5)
        self.manager.stop()
        self.assertFalse(self.manager.is_running)

    def test_get_status(self):
        self.manager.start()
        time.sleep(0.3)
        status = self.manager.get_status()
        self.assertIn('running', status)
        self.assertIn('pool', status)
        self.assertIn('health', status)
        self.assertIn('statistics', status)
        self.manager.stop()

    def test_force_switch_proxy(self):
        self.manager.start()
        time.sleep(0.2)
        new_proxy = self.manager.force_switch_proxy("测试切换")
        self.assertIsNotNone(new_proxy)
        self.manager.stop()

    def test_export_logs(self):
        export_path = os.path.join(tempfile.mkdtemp(), "test_export.json")
        result = self.manager.export_logs(export_path)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(export_path))
        os.remove(export_path)

    def test_cleanup_resources(self):
        self.manager.start()
        time.sleep(0.2)
        self.manager.cleanup_resources()
        self.manager.stop()

    def test_get_recent_logs(self):
        self.manager.start()
        time.sleep(0.5)
        logs = self.manager.get_recent_logs(100)
        self.assertIsInstance(logs, list)
        self.manager.stop()

    def test_double_start(self):
        self.manager.start()
        time.sleep(0.2)
        result = self.manager.start()
        self.assertFalse(result)
        self.manager.stop()

    def test_stop_when_not_running(self):
        self.manager.stop()
        self.assertFalse(self.manager.is_running)


class TestIntervalAccuracy(unittest.TestCase):
    def test_request_interval_accuracy(self):
        logger = RotationLogger(log_file=os.path.join(tempfile.mkdtemp(), "test_acc.log"))
        scheduler = RequestScheduler("https://example.com", interval=0.5, timeout=5, logger=logger)
        scheduler._session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        scheduler._session.get.return_value = mock_response

        intervals = []
        last_time = time.monotonic()

        def callback(addr, resp_time):
            nonlocal last_time
            now = time.monotonic()
            intervals.append(now - last_time)
            last_time = now

        proxy_info = {'proxy': '1.1.1.1:8080', 'protocol': 'http'}
        for _ in range(5):
            scheduler._execute_single_request(lambda: proxy_info, callback, None)
            time.sleep(0.5)

        if len(intervals) > 1:
            for interval in intervals[1:]:
                self.assertAlmostEqual(interval, 0.5, delta=0.1)


if __name__ == '__main__':
    unittest.main()
