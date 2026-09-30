"""Opt-in offline test guard and measured PF count; no change to production runs."""
import json
import socket
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption('--offline-pf-report', default=None)
    parser.addoption('--v3-root', default=None)


def pytest_sessionstart(session):
    config=session.config
    if not config.getoption('--offline-pf-report'):return
    config._offline_counts={'actual_pf_calls':0,'network_connect_attempts':0}
    target=Path(config.getoption('--offline-pf-report'));target.parent.mkdir(parents=True,exist_ok=True)
    def persist():
        temp=target.with_suffix('.tmp')
        temp.write_text(json.dumps({**config._offline_counts,'status':'running'},indent=2)+'\n',encoding='utf-8')
        temp.replace(target)
    config._persist_offline=persist
    persist()
    config._original_connect=socket.socket.connect
    def deny(*args,**kwargs):
        config._offline_counts['network_connect_attempts']+=1
        persist()
        raise AssertionError('network access prohibited in offline test run')
    socket.socket.connect=deny
    import pandapower as pp
    config._original_runpp=pp.runpp
    def measured(*args,**kwargs):
        config._offline_counts['actual_pf_calls']+=1
        persist()
        return config._original_runpp(*args,**kwargs)
    pp.runpp=measured


def pytest_sessionfinish(session,exitstatus):
    config=session.config;path=config.getoption('--offline-pf-report')
    if not path:return
    import pandapower as pp
    socket.socket.connect=config._original_connect;pp.runpp=config._original_runpp
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({**config._offline_counts,'exitstatus':int(exitstatus),'collected':session.testscollected},indent=2)+'\n',encoding='utf-8')
