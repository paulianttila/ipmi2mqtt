from mqtt_framework import Framework
from mqtt_framework import Config
from mqtt_framework.callbacks import Callbacks
from mqtt_framework.app import TriggerSource

from prometheus_client import Counter

from datetime import datetime
import time

import subprocess
from cacheout import Cache
import csv

class MyConfig(Config):

    def __init__(self):
        super().__init__(self.APP_NAME)

    APP_NAME = 'ipmi2mqtt'

    # App specific variables

    IPMI_HOST = '127.0.0.1'
    IPMI_USER = None
    IPMI_PASS = None
    CACHE_TIME = 300
    TIMEOUT = 5

class MyApp:

    def init(self, callbacks: Callbacks) -> None:
        self.logger = callbacks.get_logger()
        self.config = callbacks.get_config()
        self.metrics_registry = callbacks.get_metrics_registry()
        self.add_url_rule = callbacks.add_url_rule
        self.publish_value_to_mqtt_topic = callbacks.publish_value_to_mqtt_topic
        self.subscribe_to_mqtt_topic = callbacks.subscribe_to_mqtt_topic
        self.succesfull_fecth_metric = Counter('succesfull_fecth', '', registry=self.metrics_registry)
        self.fecth_errors_metric = Counter('fecth_errors', '', registry=self.metrics_registry)

        self.exit = False
        self.valueCache = Cache(maxsize=256, ttl=self.config['CACHE_TIME'])

    def get_version(self) -> str:
        return '1.0.0'

    def stop(self) -> None:
        self.logger.debug('Stopping...')
        self.exit = True
        self.logger.debug('Exit')

    def subscribe_to_mqtt_topics(self) -> None:
        pass

    def mqtt_message_received(self, topic: str, message: str) -> None:
        pass

    def do_healthy_check(self) -> bool:
        return True

    # Do work
    def do_update(self, trigger_source: TriggerSource) -> None:
        self.logger.debug('update called, trigger_source=%s', trigger_source)
        if trigger_source == trigger_source.MANUAL:
            self.valueCache.clear()

        retval, result = self.get_ipmi_values()
        if retval == 0:
            self.succesfull_fecth_metric.inc()
            vals = self.parse_ipmi_values(csv.DictReader(result.splitlines(), delimiter=','))
            for name, value in vals.items():
                self.publish_value(name, value)
            
            self.publish_value_to_mqtt_topic(
                'lastUpdateTime',
                str(datetime.now().replace(microsecond=0).isoformat()),
                True)
        else:
            self.fecth_errors_metric.inc()

    def get_ipmi_values(self):
        start = time.time()
        retval, result = self.execute_command(
            [
                'ipmi-sensors',
                '--comma-separated-output',
                '--hostname=' + self.config['IPMI_HOST'],
                '--username=' + self.config['IPMI_USER'],
                '--password=' + self.config['IPMI_PASS']
            ], 
            self.config['TIMEOUT']
        )
        end = time.time()
        self.logger.debug('ipmi-sensors result (retval=%d, time=%f): %s', retval, (end - start), result)
        return retval, result

    def execute_command(self, cmd, timeout=5, cwd=None):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return (r.returncode, r.stdout)

    def is_not_blank(self, str):
        return bool(str and str.strip())

    def parse_ipmi_values(self, reader):
        dict = {}
        for row in reader:
            name = row['Name'].replace(' ', '_')
            value = row['Reading'].replace(' ', '_')
            if self.is_not_blank(name) and self.is_not_blank(value) and value != 'N/A':
                dict[name] = value
        return dict

    def publish_value(self, key, value):
        previousvalue = self.valueCache.get(key)
        publish=False
        if previousvalue is None:
            self.logger.debug('%s: no cache value available', key)
            publish=True
        else:
            if value == previousvalue:
                self.logger.debug('%s = %s : skip update because of same value', key, value)
            else:
                publish=True
        
        if publish:
            self.logger.info('%s = %s', key, value)
            self.publish_value_to_mqtt_topic(
                key,
                value,
                False)
            self.valueCache.set(key, value)


if __name__ == '__main__':
    Framework().start(MyApp(), MyConfig(), blocked=True)
