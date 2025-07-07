from functools import lru_cache, wraps
import shelve
import datetime as dt
from pathlib import Path
from os import mkdir
from yandex_tracker_client.exceptions import Forbidden
from dateutil.relativedelta import relativedelta
from types import SimpleNamespace

_future_date = dt.datetime.now(dt.timezone.utc) + relativedelta(years=3)


def issue_cache(file_name):
    # Check cache folder is present or create it
    if not Path('cache').exists():
        mkdir('cache')
    # Check date of cache to clear old cache
    with shelve.open(file_name, protocol=-1) as test:
        flag = 'c' if 'date' in test and test['date'] == dt.datetime.now(dt.timezone.utc).date() \
            else 'n'
    # Open work instance and save the date to new shelve
    d = shelve.open(file_name, protocol=-1, flag=flag)
    if flag == 'n':
        d['date'] = dt.datetime.now(dt.timezone.utc).date()

    def decorator(func):
        @wraps(func)
        def wrapper(issue):
            key = issue.key
            if key not in d:
                d[key] = func(issue)
            return d[key]

        return wrapper

    return decorator


@lru_cache(maxsize=None)  # Caching access to YT
@issue_cache('cache/gti')
def issue_times(issue):
    """ Return reverse-sorted by time list of issue spends, estimates, status and resolution changes"""
    sp = [{'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
           'kind': field['field'].id,
           'value': field['to'] if field['field'].id in ['spent', 'estimation']
           else field['to'].key if field['to'] is not None else ''}
          for log in issue.changelog for field in log.fields
          if field['field'].id in ['spent', 'estimation', 'resolution', 'status']]
    sp.sort(key=lambda d: d['date'], reverse=True)
    return sp


@lru_cache(maxsize=None)  # Caching access to YT
@issue_cache('cache/gli')
def linked_issues(issue):
    def _accessible(someone):
        try:
            x = someone.summary is not None
        except Forbidden:
            x = False
        return x

    """ Return list of issue linked subtasks """
    return [link.object for link in issue.links
            if link.type.id == 'subtask' and
            dict(outward=link.type.inward, inward=link.type.outward)[link.direction] == 'Подзадача' and
            _accessible(link.object)]


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    try:
        d = min([t[-1]['date'] for issue in issues
                 if len(t := issue_times(issue))])
    except ValueError:
        d = dt.datetime.now(dt.timezone.utc)
    return d

