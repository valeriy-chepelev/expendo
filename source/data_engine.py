"""
Data Engine module for expendo2 project
(c) VCh 2025
"""

from functools import lru_cache
from yandex_tracker_client.exceptions import Forbidden
import datetime as dt
from dateutil.relativedelta import relativedelta
import logging
from types import SimpleNamespace
from prettytable import PrettyTable

_future_date = dt.datetime.now(dt.timezone.utc) + relativedelta(years=3)
TODAY = dt.datetime.now(dt.timezone.utc).date()  # Today, actually

# ===================================================
#             Data Access Procedures
# ===================================================


@lru_cache(maxsize=None)  # Caching access to YT
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


@lru_cache(maxsize=None)  # Caching calculations and YT access
def issue_original(issue):
    """Return start, end and initial estimate value at the issue start moment.
    If unable to detect start or end - return future dates."""
    # start date is date of first InProgress status
    # if start date unknown - return future for backlogged tasks, or far past for other statuses?
    start_date = next((t['date'] for t in reversed(issue_times(issue))
                       if t['kind'] == 'status' and t['value'] in ['inProgress', 'testing']),
                      _future_date)
    # final date is date of last Fixed resolution
    # if final date unknown - return future
    final_date = next((t['date'] for t in issue_times(issue)
                       if t['kind'] == 'resolution' and t['value'] in ['fixed']),
                      _future_date)
    # if final_date found, but start_data wasn't (issue closed successfully without inProgres)
    # correct start_date to the final_date
    start_date = min(start_date, final_date)
    # find last estimation before start
    # if task not estimated before start - find any first estimation
    est = next((s['value'] for s in issue_times(issue)
                if s['kind'] == 'estimation' and s['date'].date() <= start_date.date()),
               next((s['value'] for s in reversed(issue_times(issue))
                     if s['kind'] == 'estimation'), 0))
    r = {'start': start_date.date(),
         'end': final_date.date(),
         'original': est,
         'created': dt.datetime.strptime(issue.createdAt, '%Y-%m-%dT%H:%M:%S.%f%z').date(),
         'valuable': issue.type.key in ['task', 'bug'] and
                     (issue.resolution is None or issue.resolution.key in ['fixed']),
         'finished': issue.status.key in ['resolved', 'closed'] and
                     issue.resolution is not None and
                     issue.resolution.key in ['fixed']}
    logging.info(f'{issue.type.key} {issue.key} burn measured to: %s', r)
    return SimpleNamespace(**r)


@lru_cache(maxsize=None)  # Caching access to YT
def _tags(issue):
    """ Return one issue tags """
    return list(issue.tags)


@lru_cache(maxsize=None)  # Caching access to YT
def _queue(issue):
    """ Return one issue queues """
    return [issue.queue.key]


@lru_cache(maxsize=None)  # Caching access to YT
def _components(issue):
    """ Return one issue components """
    return [comp.name for comp in issue.components]

# ===================================================
#             Data Processing Procedures
# ===================================================


def estimate(issues, date):
    """
    Summ issues estimate up to the date (including).
    Assumed closed task always has zero estimation.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([next((s['value'] for s in issue_times(issue)
                      if s['kind'] == 'estimation' and s['date'].date() <= date), 0)
                for issue in issues])


def spent(issues, date):
    """
    Summ issues spent up to the date (including) total.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([next((s['value'] for s in issue_times(issue)
                      if s['kind'] == 'spent' and s['date'].date() <= date), 0)
                for issue in issues])


def original(issues, date):
    """
    Summ original (first before WIP) issues estimate up to the date (including).
    Consider issue closing date. Ignores rejected issues.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([e.original for issue in issues
                if (e := issue_original(issue)).valuable & (e.created <= date <= e.end)])


def burned(issues, date):
    """
    Summ closed original (first before WIP) issues estimate up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([e.original for issue in issues
                if (e := issue_original(issue)).valuable and e.finished and (e.end <= date)])


# ===================================================
#             Data Manager Class
# ===================================================

def _match(category):
    """Function fabric - return issue match function"""
    def test(*args):
        return f'Test: {list(args)}'
    def type(issue, val):
        return issue.type.key == val
    def tag(issue, val):
        return val in _tags(issue)
    def component(issue, val):
        return val in _components(issue)
    def queue(issue, val):
        return val == _queue(issue)

    # TODO: add projects and epics matchers
    assert category in locals()
    return locals()[category]


class DataManager:
    def __init__(self, query, issues):
        super(DataManager, self).__init__()
        self._period_str = ''
        self.query = query
        self.issues = issues
        self.tags = []
        self.queues = []
        self.stat = ''
        self._update_stat()
        self._update_categories()

    def _filter(self, category, value=None):
        matcher = _match(category)
        return [t for t in self.issues if matcher(t, value)]

    def _update_categories(self):
        self.tags = list({tag for t in self.issues for tag in _tags(t)})
        self.queues = list({_queue(t) for t in self.issues})
        self.components = list({component for t in self.issues for component in _components(t)})
        # TODO: add projects and epics

    def recalc(self, **kwargs):
        self._update_period(local_p=kwargs.get('local_period'),
                            global_p=kwargs.get('global_period'))
        # TODO: updates and calculations of data rows
        pass

    def _update_stat(self):
        def row(title, issues):
            return [title, len(issues),
                    len([1 for s in issues if s.resolution is None]),
                    estimate(issues, TODAY),
                    spent(issues, TODAY),
                    original(issues, TODAY),
                    burned(issues, TODAY)]
        tbl = PrettyTable()
        tbl.field_names = ['Type', 'Count', 'Open', 'Estimate', 'Spent', 'Original', 'Burned']
        tbl.add_row(row('Tasks', self._filter('type', 'task')))
        tbl.add_row(row('Bugs', self._filter('type', 'bug')))
        tbl.add_row(row('Total', self.issues()))
        tbl.align = 'r'
        self.stat = tbl.get_string()

    def _update_period(self, local_p, global_p):
        """
        Update internal dates and info string of period
        :param local_p: dict(p, to) or None with local period settings
        :param global_p: dict(p, to) with global period settings
        """
        p = global_p if local_p is None else local_p
        # TODO: decode period

    def get_info(self, **kwargs):
        mode = 'Daily' if kwargs.get('mode', 'daily') == 'daily'\
            else f'Sprint ({kwargs.get("length")} days based {kwargs.get("base").strftime("%d.%m.%y")})'
        # TODO: add projects and epics
        return '\n'.join([self.query, self.stat,
                          f'Settings: {mode} for {self._period_str}',
                          'Categories:',
                          f'- Queues: {", ".join(self.queues)}',
                          f'- Tags: {", ".join(self.tags)}',
                          f'- Components: {", ".join(self.components)}',
                          'Enter ? to commands list (i.e. "plot estimate"), CR to this stat, or Q to quit.'])

    def get_categories(self):
        return list(set(self.tags) | set(self.queues) | set(self.components))
        # TODO: add projects and epics

    def get_data(self):
        pass  # TODO: return data rows
