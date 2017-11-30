import argparse
from datetime import datetime
import logging
import requests
from socket import getfqdn
from time import monotonic as monotime
from time import sleep, time

from .helpers import BaseConfiguration, setup_logging, setup_log_file


logger = logging.getLogger(__name__)

default_sleep_interval = 30


def web_agent_main():
    p = argparse.ArgumentParser()
    p.add_argument('--verbose', '-v', action='count')
    p.add_argument('conf_file')
    args = p.parse_args()
    setup_logging(verbosity=args.verbose)
    conf = Configuration(args.conf_file)
    setup_log_file(conf.log.file_path)
    logger.debug('Web agent starting')
    run_web_agent(conf)


def run_web_agent(conf):
    sleep_interval = conf.sleep_interval or default_sleep_interval
    while True:
        run_web_agent_iteration(conf, sleep_interval)
        sleep(sleep_interval)


def run_web_agent_iteration(conf, sleep_interval):
    rs = requests.session()
    for n, target in enumerate(conf.watch_targets, start=1):
        logger.info('Processing target %d/%d: %s', n, len(conf.watch_targets), target.url)
        process_target(conf, sleep_interval, rs, target)


def process_target(conf, sleep_interval, rs, target):
    report_date = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    report_label = {
        'agent': 'web',
        'host': getfqdn(),
        'target': target.name or target.url,
    }
    t0 = monotime()
    r = rs.get(target.url)
    duration = monotime() - t0
    report_state = {
        'url': target.url,
        'final_url': r.url,
        'response': {
            'status_code': {
                '__value': r.status_code,
                '__check': {
                    'state': 'green' if r.status_code == 200 else 'red',
                },
            },
            'content_length': len(r.content),
            'duration': duration,
        },
    }

    if target.response_contains:
        present = target.response_contains in r.text
        report_state['response_contains'] = {
            'text': target.response_contains,
            'present': {
                '__value': present,
                '__check': {
                    'state': 'green' if present else 'red',
                },
            },
        }

    # add watchdog
    wd_interval = conf.watchdog_interval or sleep_interval + 30
    report_state['watchdog'] = {
        '__watchdog': {
            'deadline': int((time() + wd_interval) * 1000),
        },
    }


    report_data = {
        'label': report_label,
        'date': report_date,
        'state': report_state,
    }

    try:
        r = rs.post(conf.report_url, json=report_data, headers={'Authorization': 'token ' + conf.report_token})
        logger.debug('Report response: %s', r.text[:100])
        r.raise_for_status()
    except Exception as e:
        logger.error('Failed to post report to %r: %r', conf.report_url, e)
        logger.info('Report token: %s...%s', conf.report_token[:3], conf.report_token[:-3])
        logger.info('Report data: %r', report_data)


class Configuration (BaseConfiguration):

    top_level_key = 'overwatch_web_agent'

    def _load(self, data, base_path):
        super()._load(data, base_path)
        if not isinstance(data['watch'], list):
            raise Exception('Configuration item overwatch_web_agent.watch must be a list')
        self.watch_targets = [WatchTarget(d) for d in data['watch']]


class WatchTarget:

    def __init__(self, data):
        self.name = data.get('name')
        self.url = data['url']
        self.response_contains = data.get('response_contains')