import datetime as dt
import math
from functools import lru_cache

from alive_progress import alive_bar
from natsort import natsorted


def _get_iso_split(s, split):
    """ Splitter helper for converting ISO dt notation"""
    if split in s:
        n, s = s.split(split)
    else:
        n = 0
    if n == '':
        n = 0
    return int(n), s


def iso_hrs(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored."""
    if s is None:
        return 0
    # Remove prefix
    s = s.split('P')[-1]
    # Step through letter dividers
    weeks, s = _get_iso_split(s, 'W')
    days, s = _get_iso_split(s, 'D')
    _, s = _get_iso_split(s, 'T')
    hours, s = _get_iso_split(s, 'H')
    # Convert all to hours
    return (weeks * 5 + days) * 8 + hours


def iso_days(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored.
    Hours less than 8 rounded up to 1 day."""
    return math.ceil(iso_hrs(s) / 8)


@lru_cache(maxsize=None)  # Cashing access to YT
def _get_issue_times(issue):
    """ Return reverse-sorted list of issue spent and estimates """
    sp = [{'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
           'kind': field['field'].id,
           'value': 0 if (v := field['to']) is None else iso_hrs(v)}
          for log in issue.changelog for field in log.fields
          if field['field'].id in ['spent', 'estimation']]
    sp.sort(key=lambda d: d['date'], reverse=True)
    return sp


@lru_cache(maxsize=None)  # Cashing access to YT
def _get_linked(issue):
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
    if w_bar:
        with alive_bar(len(issues), title='Components', theme='classic') as bar:
            for issue in issues:
                comp.update({comp.name for comp in issue.components})
                comp.update(set(components(_get_linked(issue))))
                bar()
    else:
        for issue in issues:
            comp.update({comp.name for comp in issue.components})
            comp.update(set(components(_get_linked(issue))))
    return sorted(list(comp))


@lru_cache(maxsize=None)  # Cashing access to YT
def cashed_components(issue):
    """ Return one issue components """
    return components([issue])


def queues(issues: list, w_bar=False):
    """ Return list of queues used by issues and all of its descendants """
    q = set()
    if w_bar:
        with alive_bar(len(issues), title='Queues', theme='classic') as bar:
            for issue in issues:
                q.add(issue.queue.key)
                q.update(set(queues(_get_linked(issue))))
                bar()
    else:
        for issue in issues:
            q.add(issue.queue.key)
            q.update(set(queues(_get_linked(issue))))
    return sorted(list(q))


@lru_cache(maxsize=None)  # Cashing access to YT
def cashed_queues(issue):
    """ Return one issue queues """
    return queues([issue])


def issue_spent(issue, date, mode, cat, default_comp=()):
    """ Return summary spent of issue (hours) including spent of all child issues,
    due to the date, containing specified component."""
    if mode == 'components':
        own_cat = cashed_components(issue)
    elif mode == 'queues':
        own_cat = cashed_queues(issue)
    else:
        own_cat = list()
    sp = 0
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp):
        spends = _get_issue_times(issue)
        sp = next((s['value'] for s in spends
                   if s['kind'] == 'spent' and s['date'].date() <= date.date()), 0) + \
             sum([issue_spent(linked, date, mode, cat,
                              own_cat if mode == 'components' and len(own_cat) > 0 \
                                  else default_comp)
                  for linked in _get_linked(issue)])
    return sp


def issue_estimate(issue, date, mode, cat, default_comp=()):
    """ Return estimate of issue (hours) as summary estimates of all child issues,
    for the date, containing specified component."""
    if mode == 'components':
        own_cat = cashed_components(issue)
    elif mode == 'queues':
        own_cat = cashed_queues(issue)
    else:
        own_cat = list()
    est = 0
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp):
        if len(_get_linked(issue)) == 0:
            estimates = _get_issue_times(issue)
            est = next((s['value'] for s in estimates
                        if s['kind'] == 'estimation' and s['date'].date() <= date.date()), 0)
        else:
            est = sum([issue_estimate(linked, date, mode, cat,
                                      own_cat if mode == 'components' and len(own_cat) > 0 \
                                          else default_comp)
                       for linked in _get_linked(issue)])
    return est


def spent(issues: list, dates: list, mode):
    """ Return issues summary spent daily timeline as dictionary of
    {date: {issue_key: spent[days]}} for the listed issues.
    If by_component requested, collect spent for issues components and return
    timeline {date: {component: spent[days]}}.
    Issue in list should be yandex tracker reference."""
    if mode == 'queues':
        cats = queues(issues, True)
    elif mode == 'components':
        cats = components(issues, True)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Spends', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat:
                                      sum([issue_spent(issue, date, mode, cat)
                                           for issue in issues
                                           if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key:
                                      issue_spent(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def estimate(issues: list, dates: list, mode):
    """ Return issues estimate daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect estimates for issues components and return
    timeline {date: {component: estimate[days]}}.
    Issue in list should be yandex tracker reference."""
    if mode == 'queues':
        cats = queues(issues, True)
    elif mode == 'components':
        cats = components(issues, True)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Estimates', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat:
                                      sum([issue_estimate(issue, date, mode, cat)
                                           for issue in issues
                                           if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key:
                                      issue_estimate(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def precashe(issues, with_bar=False):
    """ Execute calls to all cashed functions"""
    if with_bar:
        with alive_bar(3 * len(issues), title='Cashing', theme='classic') as bar:
            for issue in issues:
                cashed_queues(issue)
                bar()
                cashed_components(issue)
                bar()
                if len(_get_linked(issue)) == 0:
                    issue_sprints(issue)
                    _get_issue_times(issue)
                else:
                    precashe(_get_linked(issue))
                bar()
    else:
        for issue in issues:
            cashed_queues(issue)
            cashed_components(issue)
            if len(_get_linked(issue)) == 0:
                issue_sprints(issue)
                _get_issue_times(issue)
            else:
                precashe(_get_linked(issue))


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    with alive_bar(len(issues), title='Start date', theme='classic') as bar:
        try:
            d = min([t[-1]['date'] for issue in issues
                     if (len(t := _get_issue_times(issue)) > 0) ^ (bar() in ['nothing'])])
        except ValueError:
            d = dt.datetime.now(dt.timezone.utc)
    return d


@lru_cache(maxsize=None)  # Cashing access to YT
def issue_sprints(issue) -> list:
    """ Return list of issue sprints, including all the subtasks,
    according to the logs """
    # TODO: get full sprints info including dates
    spr = {sc[0].name} if (sc := issue.sprint) is not None and len(sc) > 0 else set()
    for log in issue.changelog:
        for field in log.fields:
            if field['field'].id == 'sprint':
                if (to := field['to']) is not None and len(to) > 0:
                    spr.add(to[0].name)
                if (fr := field['from']) is not None and len(fr) > 0:
                    spr.add(fr[0].name)
    for linked in _get_linked(issue):
        spr.update(issue_sprints(linked))
    return natsorted(list(spr))


def sprints(issues: list) -> list:
    """ Return list of sprints, where tasks was present, including all the subtasks,
    according to the logs """
    s = set()
    with alive_bar(len(issues), title='Sprints', theme='classic') as bar:
        for issue in issues:
            s.update(set(issue_sprints(issue)))
            bar()
    return natsorted(list(s))
