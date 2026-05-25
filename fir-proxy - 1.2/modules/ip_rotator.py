# modules/ip_rotator.py

import threading
import time
import logging
import json
import os
from datetime import datetime
from collections import deque
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class RequestStatus(Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    HTTP_ERROR = "http_error"
    SERVER_ERROR = "server_error"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RequestRecord:
    __slots__ = ('timestamp', 'target_url', 'proxy_address', 'status_code',
                 'response_time', 'proxy_ip', 'status', 'failure_reason', 'used_proxy')

    def __init__(self, timestamp, target_url, proxy_address, status_code,
                 response_time, proxy_ip, status, failure_reason="", used_proxy=False):
        self.timestamp = timestamp
        self.target_url = target_url
        self.proxy_address = proxy_address
        self.status_code = status_code
        self.response_time = response_time
        self.proxy_ip = proxy_ip
        self.status = status
        self.failure_reason = failure_reason
        self.used_proxy = used_proxy

    def to_dict(self):
        return {
            'timestamp': self.timestamp,
            'target_url': self.target_url,
            'proxy_address': self.proxy_address,
            'status_code': self.status_code,
            'response_time': round(self.response_time, 4),
            'proxy_ip': self.proxy_ip,
            'status': self.status.value if isinstance(self.status, RequestStatus) else self.status,
            'failure_reason': self.failure_reason,
            'used_proxy': self.used_proxy,
        }

    def to_log_string(self):
        status_icon = {
            RequestStatus.SUCCESS: "[OK]",
            RequestStatus.TIMEOUT: "[TIMEOUT]",
            RequestStatus.CONNECTION_ERROR: "[CONN_ERR]",
            RequestStatus.HTTP_ERROR: "[HTTP_ERR]",
            RequestStatus.SERVER_ERROR: "[SERVER_ERR]",
            RequestStatus.DEGRADED: "[DEGRADED]",
            RequestStatus.SKIPPED: "[SKIP]",
        }
        icon = status_icon.get(self.status, "[???]")
        parts = [
            f"{icon}",
            f"时间={self.timestamp}",
            f"代理={self.proxy_address or 'N/A'}",
            f"状态码={self.status_code or 'N/A'}",
            f"耗时={self.response_time:.3f}s",
        ]
        if self.failure_reason:
            parts.append(f"原因={self.failure_reason}")
        return " | ".join(parts)


class RotationLogger:
    def __init__(self, log_file="ip_rotation.log", max_memory_records=1000):
        self.log_file = log_file
        self.records = deque(maxlen=max_memory_records)
        self.lock = threading.Lock()
        self._log_queue = None
        self._file_logger = None
        self._setup_file_logger()

    def _setup_file_logger(self):
        self._file_logger = logging.getLogger('ip_rotation')
        self._file_logger.setLevel(logging.DEBUG)
        for h in list(self._file_logger.handlers):
            h.close()
            self._file_logger.removeHandler(h)
        try:
            handler = logging.FileHandler(self.log_file, encoding='utf-8')
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)-8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            self._file_logger.addHandler(handler)
        except Exception:
            pass

    def set_external_log_queue(self, log_queue):
        self._log_queue = log_queue

    def log(self, message, level=LogLevel.INFO):
        record = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'level': level.value,
            'message': message,
        }
        with self.lock:
            self.records.append(record)

        log_method = getattr(self._file_logger, level.value.lower(), self._file_logger.info)
        try:
            log_method(message)
        except Exception:
            pass

        if self._log_queue:
            prefix = "[IP轮换]"
            self._log_queue.put(f"{prefix} {message}")

    def log_request(self, record: RequestRecord):
        with self.lock:
            self.records.append({
                'timestamp': record.timestamp,
                'level': 'REQUEST',
                'detail': record.to_dict(),
            })
        try:
            self._file_logger.info(f"REQUEST | {record.to_log_string()}")
        except Exception:
            pass

        if self._log_queue:
            self._log_queue.put(f"[IP轮换] 请求记录: {record.to_log_string()}")

    def log_proxy_switch(self, from_proxy, to_proxy, reason):
        msg = f"代理切换: {from_proxy or 'N/A'} -> {to_proxy or 'N/A'} | 原因: {reason}"
        self.log(msg, LogLevel.INFO)
        if self._log_queue:
            self._log_queue.put(f"[IP轮换] *** {msg} ***")

    def get_recent_records(self, count=50):
        with self.lock:
            return list(self.records)[-count:]

    def get_statistics(self):
        with self.lock:
            total = 0
            success = 0
            failures = 0
            for r in self.records:
                if isinstance(r, dict) and 'detail' in r:
                    total += 1
                    status = r['detail'].get('status', '')
                    if status == RequestStatus.SUCCESS.value:
                        success += 1
                    elif status in (RequestStatus.TIMEOUT.value, RequestStatus.CONNECTION_ERROR.value,
                                    RequestStatus.HTTP_ERROR.value, RequestStatus.SERVER_ERROR.value):
                        failures += 1
            return {
                'total_requests': total,
                'successful': success,
                'failed': failures,
                'success_rate': f"{(success / total * 100):.1f}%" if total > 0 else "N/A",
            }

    def export_log(self, filepath):
        try:
            with self.lock:
                data = list(self.records)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            self.log(f"日志已导出到: {filepath}", LogLevel.INFO)
            return True
        except Exception as e:
            self.log(f"日志导出失败: {e}", LogLevel.ERROR)
            return False


class ProxyPoolManager:
    def __init__(self, rotator, logger):
        self._rotator = rotator
        self._logger = logger
        self._lock = threading.Lock()
        self._current_proxy = None
        self._blacklist = {}
        self._blacklist_ttl = 300
        self._switch_count = 0

    def get_current_proxy(self):
        with self._lock:
            if self._current_proxy:
                addr = self._current_proxy.get('proxy')
                if addr in self._blacklist:
                    expiry = self._blacklist[addr]
                    if time.time() < expiry:
                        self._logger.log(
                            f"当前代理 {addr} 在黑名单中，尝试切换",
                            LogLevel.WARNING
                        )
                        return self._switch_to_next()
                    else:
                        del self._blacklist[addr]
                rotator_proxy = self._rotator.get_proxy_by_address(addr)
                if rotator_proxy and rotator_proxy.get('status') == 'Working':
                    return self._current_proxy
                else:
                    return self._switch_to_next()
            return self._switch_to_next()

    def report_success(self, proxy_address, response_time):
        with self._lock:
            self._rotator.update_proxy(proxy_address, {
                'status': 'Working',
                'consecutive_failures': 0,
            })
            if proxy_address in self._blacklist:
                del self._blacklist[proxy_address]

    def report_failure(self, proxy_address, reason=""):
        with self._lock:
            self._rotator.report_failure(proxy_address)
            self._blacklist[proxy_address] = time.time() + self._blacklist_ttl
            self._logger.log(
                f"代理 {proxy_address} 标记为失败 | {reason}",
                LogLevel.WARNING
            )

    def _switch_to_next(self):
        old_proxy = self._current_proxy.get('proxy') if self._current_proxy else None
        next_proxy = self._rotator.get_next_proxy()
        if next_proxy:
            self._current_proxy = next_proxy
            self._switch_count += 1
            self._logger.log_proxy_switch(
                old_proxy,
                next_proxy.get('proxy'),
                "轮换到下一个可用代理"
            )
            return next_proxy
        self._logger.log("代理池中无可用代理", LogLevel.ERROR)
        return None

    def force_switch(self, reason="手动触发"):
        with self._lock:
            return self._switch_to_next()

    def get_pool_status(self):
        active_count = self._rotator.get_active_proxies_count()
        blacklist_count = len([
            addr for addr, expiry in self._blacklist.items()
            if time.time() < expiry
        ])
        return {
            'active_proxies': active_count,
            'blacklisted': blacklist_count,
            'current_proxy': self._current_proxy.get('proxy') if self._current_proxy else None,
            'total_switches': self._switch_count,
        }

    def cleanup_blacklist(self):
        now = time.time()
        with self._lock:
            expired = [addr for addr, expiry in self._blacklist.items() if now >= expiry]
            for addr in expired:
                del self._blacklist[addr]
            return len(expired)


class HealthMonitor:
    def __init__(self, logger, failure_threshold=3, degradation_after_failures=5):
        self._logger = logger
        self._failure_threshold = failure_threshold
        self._degradation_after_failures = degradation_after_failures
        self._consecutive_failures = 0
        self._total_failures = 0
        self._total_successes = 0
        self._last_switch_time = 0
        self._switch_cooldown = 1.0
        self._lock = threading.Lock()
        self._domain_unreachable_count = 0
        self._domain_unreachable_threshold = 10
        self._domain_alert_triggered = False

    def record_success(self):
        with self._lock:
            self._consecutive_failures = 0
            self._total_successes += 1
            self._domain_unreachable_count = 0
            if self._domain_alert_triggered:
                self._domain_alert_triggered = False
                self._logger.log("域名恢复可访问，告警已解除", LogLevel.INFO)

    def record_failure(self, failure_type):
        with self._lock:
            self._consecutive_failures += 1
            self._total_failures += 1

            if failure_type in (RequestStatus.TIMEOUT, RequestStatus.CONNECTION_ERROR):
                self._domain_unreachable_count += 1
                if (self._domain_unreachable_count >= self._domain_unreachable_threshold
                        and not self._domain_alert_triggered):
                    self._domain_alert_triggered = True
                    self._logger.log(
                        f"[告警] 域名已连续 {self._domain_unreachable_count} 次无法访问，可能永久不可达",
                        LogLevel.CRITICAL
                    )
            else:
                self._domain_unreachable_count = 0

    def should_switch_proxy(self):
        with self._lock:
            now = time.time()
            if now - self._last_switch_time < self._switch_cooldown:
                return False
            if self._consecutive_failures >= self._failure_threshold:
                self._last_switch_time = now
                return True
            return False

    def should_degrade(self):
        with self._lock:
            return self._consecutive_failures >= self._degradation_after_failures

    def should_alert_domain(self):
        with self._lock:
            return self._domain_alert_triggered

    def get_health_status(self):
        with self._lock:
            return {
                'consecutive_failures': self._consecutive_failures,
                'total_failures': self._total_failures,
                'total_successes': self._total_successes,
                'domain_unreachable_count': self._domain_unreachable_count,
                'domain_alert_triggered': self._domain_alert_triggered,
                'success_rate': (
                    f"{self._total_successes / (self._total_successes + self._total_failures) * 100:.1f}%"
                    if (self._total_successes + self._total_failures) > 0 else "N/A"
                ),
            }

    def reset(self):
        with self._lock:
            self._consecutive_failures = 0
            self._total_failures = 0
            self._total_successes = 0
            self._domain_unreachable_count = 0
            self._domain_alert_triggered = False


class RequestScheduler:
    def __init__(self, target_url, interval=0.5, timeout=10, logger=None):
        self.target_url = target_url
        self.interval = interval
        self.timeout = timeout
        self._logger = logger
        self._running = False
        self._stop_event = threading.Event()
        self._session = None
        self._request_thread = None
        self._lock = threading.Lock()
        self._total_requests = 0

    def _create_session(self):
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        })
        retry_strategy = Retry(total=0, backoff_factor=0, status_forcelist=[])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def start(self, get_proxy_func, on_success_callback=None, on_failure_callback=None):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._session = self._create_session()
        self._request_thread = threading.Thread(
            target=self._run_loop,
            args=(get_proxy_func, on_success_callback, on_failure_callback),
            daemon=True,
            name="IPRotation-RequestScheduler"
        )
        self._request_thread.start()
        if self._logger:
            self._logger.log(
                f"请求调度器已启动 | 目标={self.target_url} | 间隔={self.interval}s | 超时={self.timeout}s",
                LogLevel.INFO
            )

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        if self._request_thread and self._request_thread.is_alive():
            self._request_thread.join(timeout=5)
        if self._logger:
            self._logger.log("请求调度器已停止", LogLevel.INFO)

    def _run_loop(self, get_proxy_func, on_success, on_failure):
        while self._running and not self._stop_event.is_set():
            cycle_start = time.monotonic()
            try:
                self._execute_single_request(get_proxy_func, on_success, on_failure)
            except Exception as e:
                if self._logger:
                    self._logger.log(f"请求循环异常: {e}", LogLevel.ERROR)
            elapsed = time.monotonic() - cycle_start
            remaining = self.interval - elapsed
            if remaining > 0:
                self._stop_event.wait(remaining)

    def _execute_single_request(self, get_proxy_func, on_success, on_failure):
        proxy_info = get_proxy_func()
        if not proxy_info:
            if on_failure:
                on_failure(None, RequestStatus.DEGRADED, "代理池无可用代理")
            return

        proxy_address = proxy_info.get('proxy', 'N/A')
        protocol = proxy_info.get('protocol', 'http').lower()
        used_proxy = True

        proxies_dict = None
        if proxy_address and proxy_address != 'N/A':
            proxy_url = f"{protocol}://{proxy_address}"
            proxies_dict = {'http': proxy_url, 'https': proxy_url}

        request_start = time.monotonic()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        status_code = None
        result_status = RequestStatus.SUCCESS
        failure_reason = ""

        try:
            response = self._session.get(
                self.target_url,
                proxies=proxies_dict,
                timeout=self.timeout,
                allow_redirects=True,
                verify=False,
            )
            status_code = response.status_code
            response_time = time.monotonic() - request_start

            if status_code >= 500:
                result_status = RequestStatus.SERVER_ERROR
                failure_reason = f"服务器返回 {status_code}"
            elif status_code >= 400:
                result_status = RequestStatus.HTTP_ERROR
                failure_reason = f"客户端错误 {status_code}"
            else:
                result_status = RequestStatus.SUCCESS

        except requests.exceptions.Timeout:
            response_time = time.monotonic() - request_start
            result_status = RequestStatus.TIMEOUT
            failure_reason = f"请求超时 ({self.timeout}s)"
        except requests.exceptions.ConnectionError as e:
            response_time = time.monotonic() - request_start
            result_status = RequestStatus.CONNECTION_ERROR
            error_str = str(e)
            if "ProxyError" in error_str or "SOCKS" in error_str:
                failure_reason = f"代理连接失败: {error_str[:120]}"
            else:
                failure_reason = f"连接错误: {error_str[:120]}"
        except requests.exceptions.RequestException as e:
            response_time = time.monotonic() - request_start
            result_status = RequestStatus.CONNECTION_ERROR
            failure_reason = f"请求异常: {str(e)[:120]}"
        except Exception as e:
            response_time = time.monotonic() - request_start
            result_status = RequestStatus.CONNECTION_ERROR
            failure_reason = f"未知异常: {str(e)[:120]}"

        self._total_requests += 1

        record = RequestRecord(
            timestamp=timestamp,
            target_url=self.target_url,
            proxy_address=proxy_address,
            status_code=status_code,
            response_time=response_time,
            proxy_ip=proxy_address.split(':')[0] if proxy_address and ':' in proxy_address else proxy_address,
            status=result_status,
            failure_reason=failure_reason,
            used_proxy=used_proxy,
        )

        if result_status == RequestStatus.SUCCESS:
            if on_success:
                on_success(proxy_address, response_time)
        else:
            if on_failure:
                on_failure(proxy_address, result_status, failure_reason)

        return record

    @property
    def is_running(self):
        return self._running

    @property
    def total_requests(self):
        return self._total_requests

    def update_config(self, target_url=None, interval=None, timeout=None):
        if target_url is not None:
            self.target_url = target_url
        if interval is not None:
            self.interval = interval
        if timeout is not None:
            self.timeout = timeout


class IPRotationManager:
    def __init__(self, rotator, log_queue=None):
        self._rotator = rotator
        self._logger = RotationLogger()
        if log_queue:
            self._logger.set_external_log_queue(log_queue)
        self._pool_manager = ProxyPoolManager(rotator, self._logger)
        self._health_monitor = HealthMonitor(self._logger)
        self._scheduler = None
        self._running = False
        self._lock = threading.Lock()
        self._config = {
            'target_url': 'https://www.baidu.com',
            'request_interval': 0.5,
            'request_timeout': 10,
            'failure_threshold': 3,
            'degradation_after_failures': 5,
            'degradation_mode': 'direct',
        }
        self._last_record = None

    def configure(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                if key in self._config:
                    self._config[key] = value
            if self._scheduler and self._running:
                self._scheduler.update_config(
                    target_url=self._config['target_url'],
                    interval=self._config['request_interval'],
                    timeout=self._config['request_timeout'],
                )
                self._health_monitor._failure_threshold = self._config['failure_threshold']
                self._health_monitor._degradation_after_failures = self._config['degradation_after_failures']
                self._logger.log(f"配置已热更新: {kwargs}", LogLevel.INFO)

    def start(self):
        with self._lock:
            if self._running:
                self._logger.log("IP轮换已在运行中", LogLevel.WARNING)
                return False

            if self._rotator.get_active_proxies_count() == 0:
                self._logger.log("代理池为空，无法启动IP轮换", LogLevel.ERROR)
                return False

            self._health_monitor.reset()
            self._scheduler = RequestScheduler(
                target_url=self._config['target_url'],
                interval=self._config['request_interval'],
                timeout=self._config['request_timeout'],
                logger=self._logger,
            )
            self._running = True
            self._scheduler.start(
                get_proxy_func=self._pool_manager.get_current_proxy,
                on_success_callback=self._on_request_success,
                on_failure_callback=self._on_request_failure,
            )
            self._logger.log(
                f"IP轮换管理器已启动 | 目标={self._config['target_url']}",
                LogLevel.INFO
            )
            return True

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._scheduler:
                self._scheduler.stop()
                self._scheduler = None
            self._logger.log("IP轮换管理器已停止", LogLevel.INFO)

    def _on_request_success(self, proxy_address, response_time):
        self._pool_manager.report_success(proxy_address, response_time)
        self._health_monitor.record_success()
        self._logger.log(
            f"请求成功 | 代理={proxy_address} | 耗时={response_time:.3f}s",
            LogLevel.DEBUG
        )

    def _on_request_failure(self, proxy_address, status, failure_reason):
        if proxy_address:
            self._pool_manager.report_failure(proxy_address, failure_reason)
        self._health_monitor.record_failure(status)

        if self._health_monitor.should_switch_proxy():
            old_proxy = proxy_address
            new_proxy = self._pool_manager.force_switch(
                reason=f"连续失败触发切换: {failure_reason}"
            )
            if new_proxy:
                self._logger.log_proxy_switch(
                    old_proxy,
                    new_proxy.get('proxy'),
                    f"连续失败 {self._health_monitor._consecutive_failures} 次"
                )

        if self._health_monitor.should_degrade():
            self._logger.log(
                f"[降级] 连续失败达阈值，进入降级模式 (模式: {self._config['degradation_mode']})",
                LogLevel.WARNING
            )

    def get_status(self):
        pool_status = self._pool_manager.get_pool_status()
        health_status = self._health_monitor.get_health_status()
        stats = self._logger.get_statistics()
        return {
            'running': self._running,
            'config': dict(self._config),
            'pool': pool_status,
            'health': health_status,
            'statistics': stats,
            'scheduler_running': self._scheduler.is_running if self._scheduler else False,
            'total_requests': self._scheduler.total_requests if self._scheduler else 0,
        }

    def get_recent_logs(self, count=50):
        return self._logger.get_recent_records(count)

    def export_logs(self, filepath):
        return self._logger.export_log(filepath)

    def force_switch_proxy(self, reason="手动触发"):
        return self._pool_manager.force_switch(reason)

    def cleanup_resources(self):
        self._pool_manager.cleanup_blacklist()

    @property
    def is_running(self):
        return self._running

    @property
    def config(self):
        return dict(self._config)
