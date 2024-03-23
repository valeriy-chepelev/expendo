import shelve
import functools
import datetime as dt
from pathlib import Path
from os import mkdir


def issue_cache(file_name):
    # Check cache folder is present or create it
    if not Path('cache').exists():
        mkdir('cache')
    # Check date of cache to clear old cache
    with shelve.open(file_name, protocol=-1) as test:
        flag = 'c' if 'date' in test and test['date'] == dt.datetime.now(dt.timezone.utc).date()\
            else 'n'
    # Open work instance and save the date to new shelve
    d = shelve.open(file_name, protocol=-1, flag=flag)
    if flag == 'n':
        d['date'] = dt.datetime.now(dt.timezone.utc).date()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(issue):
            key = issue.key
            if key not in d:
                d[key] = func(issue)
            return d[key]

        return wrapper

    return decorator
