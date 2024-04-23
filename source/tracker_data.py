import datetime as dt
import math
from functools import lru_cache
from alive_progress import alive_bar
from collections import Counter
from dateutil.rrule import rrule, DAILY
import logging
from issue_cache import issue_cache
from dateutil.relativedelta import relativedelta

future_date = dt.datetime.now(dt.timezone.utc) + relativedelta(days=3)


def _iso_split(s, split):
    """ Splitter helper for converting ISO dt notation"""
    if split in s:
        n, s = s.split(split)
    else:
        n = 0
    if n == '':
        n = 0
    return int(n), s


def _iso_hrs(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored."""
    if s is None:
        return 0
    # Remove prefix
    s = s.split('P')[-1]
    # Step through letter dividers
    weeks, s = _iso_split(s, 'W')
    days, s = _iso_split(s, 'D')
    _, s = _iso_split(s, 'T')
    hours, s = _iso_split(s, 'H')
    # Convert all to hours
    return (weeks * 5 + days) * 8 + hours


def _iso_days(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored.
    Hours less than 8 rounded up to 1 day."""
    return math.ceil(_iso_hrs(s) / 8)


@lru_cache(maxsize=None)  # Caching access to YT
@issue_cache('cache/gti')
def _issue_times(issue):
    """ Return reverse-sorted by time list of issue spends, estimates, status and resolution changes"""
    sp = [{'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
           'kind': field['field'].id,
           'value': _iso_hrs(field['to']) if field['field'].id in ['spent', 'estimation'] \
               else field['to'].key if field['to'] is not None else ''}
          for log in issue.changelog for field in log.fields
          if field['field'].id in ['spent', 'estimation', 'resolution', 'status']]
    sp.sort(key=lambda d: d['date'], reverse=True)
    return sp


@lru_cache(maxsize=None)  # Caching access to YT
@issue_cache('cache/gli')
def _linked_issues(issue):
    """ Return list of issue linked subtasks """
    return [link.object for link in issue.links
            if link.type.id == 'subtask' and
            dict(outward=link.type.inward, inward=link.type.outward)[link.direction] == 'Подзадача']


def epics(client, project):
    """ Return list of all project epics """
    request = f'Project: "{project}" Type: "Epic" "Sort by": Created ASC'
    return client.issues.find(query=request)


def stories(client, project):
    """ Return list of first-level project stories"""
    request = f'Project: "{project}" Type: "Story" "Sort by": Created ASC'
    return [st for st in client.issues.find(query=request)
            if (e := st.parent) is not None and e.type.key == 'epic']


def components(issues: list, w_bar=False):
    """ Return list of components assigned to issues and all of its descendants """
    comp = set()
    with alive_bar(len(issues), title='Components', theme='classic', disable=not w_bar) as bar:
        for issue in issues:
            comp.update(set(_components(issue)))
            comp.update({c for linked in _linked_issues(issue)
                         for c in components([linked])})
            bar()
    return sorted(list(comp))


@lru_cache(maxsize=None)  # Caching access to YT
@issue_cache('cache/comp')
def _components(issue):
    """ Return one issue components """
    return [comp.name for comp in issue.components]


def queues(issues: list, w_bar=False):
    """ Return list of queues used by issues and all of its descendants """
    qu = set()
    with alive_bar(len(issues), title='Queues', theme='classic', disable=not w_bar) as bar:
        for issue in issues:
            qu.update(set(_queues(issue)))
            qu.update({q for linked in _linked_issues(issue)
                       for q in queues(linked)})
            bar()
    return sorted(list(qu))


@lru_cache(maxsize=None)  # Caching access to YT
@issue_cache('cache/que')
def _queues(issue):
    """ Return one issue queues """
    return [issue.queue.key]


def _spent(issue, date, mode, cat, default_comp=()):
    """ Return summary spent of issue (hours) including spent of all child issues,
    due to the date, containing specified component."""
    # check mode
    if mode == 'components':
        own_cat = _components(issue)
    elif mode == 'queues':
        own_cat = _queues(issue)
    else:
        own_cat = list()
    # get all linked issues spends using recursion
    sp = sum([_spent(linked, date, mode, cat,
                     own_cat if mode == 'components' and len(own_cat) > 0 else default_comp)
              for linked in _linked_issues(issue)])
    # add own issue spent if issue match criteria
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp):
        sp += next((s['value'] for s in _issue_times(issue)
                    if s['kind'] == 'spent' and s['date'].date() <= date.date()), 0)
    return sp


def _estimate(issue, date, mode, cat, default_comp=()):
    """ Return estimate of issue (hours) as summary estimates of all child issues,
    for the date, containing specified component."""
    # check mode
    if mode == 'components':
        own_cat = _components(issue)
    elif mode == 'queues':
        own_cat = _queues(issue)
    else:
        own_cat = list()
    # get all linked estimates using recursion
    est = sum([_estimate(linked, date, mode, cat,
                         own_cat if mode == 'components' and len(own_cat) > 0 else default_comp)
               for linked in _linked_issues(issue)])
    # add own issue estimate according match criteria
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp) and \
            (len(_linked_issues(issue)) == 0):
        est += next((s['value'] for s in _issue_times(issue)
                     if s['kind'] == 'estimation' and s['date'].date() <= date.date()), 0)
    return est


def spent(issues: list, dates: list, mode):
    """ Return issues summary spent daily timeline as dictionary of
    {date: {issue_key: spent[days]}} for the listed issues.
    If by_component requested, collect spent for issues components and return
    timeline {date: {component: spent[days]}}.
    Issue in list should be yandex tracker reference."""
    logging.info('Spends calculation')
    if mode == 'queues':
        cats = queues(issues)
    elif mode == 'components':
        cats = components(issues)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Spends', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat: sum([_spent(issue, date, mode, cat)
                                            for issue in issues
                                            if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key: _spent(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def estimate(issues: list, dates: list, mode):
    """ Return issues estimate daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect estimates for issues components and return
    timeline {date: {component: estimate[days]}}.
    Issue in list should be yandex tracker reference."""
    logging.info('Estimates calculation')
    if mode == 'queues':
        cats = queues(issues)
    elif mode == 'components':
        cats = components(issues)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Estimates', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat: sum([_estimate(issue, date, mode, cat)
                                            for issue in issues
                                            if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key: _estimate(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    with alive_bar(len(issues), title='Start date', theme='classic') as bar:
        try:
            d = min([t[-1]['date'] for issue in issues
                     if (len(t := _issue_times(issue)) > 0) ^ (bar() in ['nothing'])])
        except ValueError:
            d = dt.datetime.now(dt.timezone.utc)
    return d


def _issue_valuable(issue) -> bool:
    """Return flag of issue is useful and finished """
    return issue.type.key in ['task', 'bug'] and \
        issue.status.key in ['resolved', 'closed'] and \
        issue.resolution.key in ['fixed']


def _sum_dict(d: list) -> dict:
    """Summarise dictionaries using Counters"""
    result = Counter()
    for item in d:
        result.update(item)
    return dict(result)


def _issue_original(issue) -> dict:
    """Return start, end and initial estimate value at the issue start moment.
    If unable to detect start or end - return today-dates."""
    # start date is date of first InProgress status
    # if start date unknown - return future for backlogged tasks, or far past for other statuses?
    start_date = next((t['date'] for t in reversed(_issue_times(issue))
                       if t['kind'] == 'status' and t['value'] in ['inProgress', 'testing']),
                      future_date)
    # final date is date of last Fixed resolution
    # if final date unknown - return future
    final_date = next((t['date'] for t in _issue_times(issue)
                       if t['kind'] == 'resolution' and t['value'] in ['fixed']),
                      future_date)
    # find last estimation before start
    est = next((s['value'] for s in _issue_times(issue)
                if s['kind'] == 'estimation' and s['date'].date() <= start_date.date()), 0)
    # if task not estimated before start - find any first estimation
    if est == 0:
        logging.info(f'{issue.type.key} {issue.key} was not estimated before start.')
        est = next((s['value'] for s in reversed(_issue_times(issue))
                    if s['kind'] == 'estimation'), 0)
    return {'start': start_date.date(),
            'end': final_date.date(),
            'original': est,
            'created': dt.datetime.strptime(issue.createdAt, '%Y-%m-%dT%H:%M:%S.%f%z').date(),
            'valuable': False}


def _burn(issue, mode, cat, splash, default_comp=()):
    """Calculate burned estimate for issue and it's descendants.
    Return {burn_date : initial estimate}
    Unclosed, canceled tasks are ignored."""
    # define mode
    if mode == 'components':
        own_cat = _components(issue)
    elif mode == 'queues':
        own_cat = _queues(issue)
    else:
        own_cat = list()
    # init daily time counter
    counter = Counter()
    # add nested burns using recursion
    for linked in _linked_issues(issue):
        counter.update(_burn(linked, mode, cat, splash,
                             own_cat if mode == 'components' and len(own_cat) > 0 else default_comp))
    # add own issue burn if issue match criteria
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp) and \
            len(_linked_issues(issue)) == 0 and _issue_valuable(issue):
        b = _issue_original(issue)
        logging.info(f'{issue.type.key} {issue.key} burn measured to: %s', b)
        if splash:
            se = b['original'] / ((b['end'] - b['start']).days + 1)
            counter.update({date.date(): se
                            for date in rrule(DAILY, dtstart=b['start'], until=b['end'])})
        else:
            counter.update({b['end']: b['original']})
    return dict(counter)


def burn(issues: list, mode, splash, dates):
    """Return burn (closed initial estimate) of issues and its descendants, sorted by mode
    {category : {date : closed estimate}}
    Unclosed, canceled tasks are ignored."""
    logging.info('Burn calculation, splash mode: %s', splash)
    if mode == 'queues':
        cats = queues(issues)
    elif mode == 'components':
        cats = components(issues)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats),
                   title='Burn', theme='classic') as bar:
        if mode in ['queues', 'components']:
            v = {cat: _sum_dict([_burn(issue, mode, cat, splash)
                                 for issue in issues if bar() not in ['nothing']])
                 for cat in cats}
        else:
            v = {issue.key: _burn(issue, mode, '', splash)
                 for issue in issues if bar() not in ['nothing']}
    return {date.date(): {row: v[row][date.date()] if date.date() in v[row].keys() else 0
                          for row in iter(v)}
            for date in dates}


def _original(issue, date, mode, cat, default_comp=()):
    """ Return initial estimate of issue (hours) as summary estimates of all child issues,
    for the date up to issue resolution set, containing specified component or queue."""
    # define mode
    if mode == 'components':
        own_cat = _components(issue)
    elif mode == 'queues':
        own_cat = _queues(issue)
    else:
        own_cat = list()
    # calculate summary nested original estimate using recursion
    est = sum([_original(linked, date, mode, cat,
                         own_cat if mode == 'components' and len(own_cat) > 0 else default_comp)
               for linked in _linked_issues(issue)])
    # add own issue original estimate if match criteria
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp) and \
            len(_linked_issues(issue)) == 0:
        e = _issue_original(issue)
        est += e['original'] if e['created'] <= date.date() <= e['end'] else 0
    return est


def original(issues: list, dates: list, mode):
    """ Return issues initial estimate daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect estimates for issues components and return
    timeline {date: {component: estimate[days]}}.
    Issue in list should be yandex tracker reference."""
    logging.info('Initial estimates calculation')
    if mode == 'queues':
        cats = queues(issues)
    elif mode == 'components':
        cats = components(issues)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Initial estimates', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat: sum([_original(issue, date, mode, cat)
                                            for issue in issues
                                            if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key: _original(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def cache_info():
    return {'times': _issue_times.cache_info(),
            'links': _linked_issues.cache_info(),
            'components': _components.cache_info(),
            'queues': _queues.cache_info()}
