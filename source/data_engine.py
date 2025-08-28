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


@lru_cache(maxsize=None)  # Caching access to YT
def issue_times(issue):
    """ Return reverse-sorted by time list of issue spends, estimates, status and resolution changes"""
    sp = [{'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
           'kind': field['field'].id,
           'value': _iso_hrs(field['to']) if field['field'].id in ['spent', 'estimation']
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
    return issue.queue.key


@lru_cache(maxsize=None)  # Caching access to YT
def _components(issue):
    """ Return one issue components """
    return [comp.name for comp in issue.components]


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    try:
        d = min([t[-1]['date'] for issue in issues
                 if len(t := issue_times(issue))])
    except ValueError:
        d = dt.datetime.now(dt.timezone.utc)
    return d


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


def _calculator(data_kind, issues, date):
    _estimate_ = estimate
    _spent_ = spent
    _original_ = original
    _burn_ = burned
    f = locals()[f'_{data_kind}_']
    assert callable(f)
    return f(issues, date)


# ===================================================
#             Data Manager Class
# ===================================================

def _match(category):
    """Function fabric - return issue match function"""

    def test(*args):
        return f'Test: {list(args)}'

    def issue_type(issue, val):
        return issue.type.key == val

    def tag(issue, val):
        return val in _tags(issue)

    def component(issue, val):
        return val in _components(issue)

    def queue(issue, val):
        return val == _queue(issue)

    # TODO: add projects and epics matchers

    assert category in locals()
    f = locals()[category]
    assert callable(f)
    return f


class DataManager:
    def __init__(self, issues):
        super(DataManager, self).__init__()
        # static data
        self.issues = issues  # issues list
        self._stat = ''  # statistical data string
        self._start_date = TODAY
        # categories
        self.tags = []
        self.queues = []
        self.components = []
        # dynamic data
        self._dates = []
        self._data = dict()
        # updates
        self._update_stat()
        self._update_categories()
        self._start_date = get_start_date(self.issues).date()

    def _filter(self, category, value, issues=None):
        matcher = _match(category)
        income = self.issues if issues is None else issues
        return [t for t in income if matcher(t, value)]

    def _auto_filter(self, value):
        # TODO: make join of filtered issues
        if value in self.tags:
            return 'Tag', self._filter('tag', value)
        elif value in self.components:
            return 'Component', self._filter('component', value)
        elif value in self.queues:
            return 'Queue', self._filter('queue', value)
        # TODO: add projects and epics
        return '', []

    def _update_categories(self):
        # collect categories info, called ones from constructor
        self.tags = list({tag for t in self.issues for tag in _tags(t)})
        self.queues = list({_queue(t) for t in self.issues})
        self.components = list({component for t in self.issues for component in _components(t)})
        # TODO: add projects and epics

    def _update_stat(self):
        # calculate common statistic data, called ones from constructor
        def row(title, issues):
            return [title, len(issues),
                    len([1 for s in issues if s.resolution is None]),
                    estimate(issues, TODAY),
                    spent(issues, TODAY),
                    original(issues, TODAY),
                    burned(issues, TODAY)]

        tbl = PrettyTable()
        tbl.field_names = ['Type', 'Count', 'Open', 'Estimate', 'Spent', 'Original', 'Burned']
        tbl.add_row(row('Tasks', self._filter('issue_type', 'task')))
        tbl.add_row(row('Bugs', self._filter('issue_type', 'bug')))
        tbl.add_row(row('Total', self.issues))
        tbl.align = 'r'
        self._stat = tbl.get_string()

    @property
    def categories(self):
        return list(set(self.tags) | set(self.queues) | set(self.components))
        # TODO: add projects and epics

    @property
    def categories_info(self):
        info = f'Categories:\n- Queues: {", ".join(self.queues)}'
        if len(self.tags):
            info += f'\n- Tags: {", ".join(self.tags)}'
        if len(self.components):
            info += f'\n- Components: {", ".join(self.components)}'
        return info
        # TODO: add projects and epics

    @property
    def stat_info(self):
        return self._stat

    def update_period(self, p_start, p_end, length=1, base=TODAY):
        """
        Update internal dates
        """
        logging.debug(f'Updating period {p_start} {p_end} {length} {base}')
        match p_end:
            case 'today' | 'now':
                end_date = TODAY
            case 'yesterday':
                end_date = TODAY - dt.timedelta(days=1)
            case _:
                end_date = dt.datetime.strptime(p_end, '%d.%m.%y').date()
        match p_start:
            case 'today' | 'now':
                start_date = min(TODAY, end_date)
            case 'yesterday':
                start_date = min(TODAY - dt.timedelta(days=1), end_date)
            case 'week':
                start_date = end_date - dt.timedelta(weeks=1)
            case 'sprint':
                start_date = end_date - dt.timedelta(days=length)
            case 'month':
                start_date = end_date - relativedelta(months=1)
            case 'quarter':
                start_date = end_date - relativedelta(months=3)
            case 'year':
                start_date = end_date - relativedelta(years=1)
            case 'all' | 'full':
                start_date = min(self._start_date, end_date)
            case _:
                start_date = min(dt.datetime.strptime(p_start, '%d.%m.%y').date(),
                                 end_date)

        # align dates to sprint
        end_date -= dt.timedelta(days=abs((end_date - base).days) % length)
        start_date -= dt.timedelta(days=length - abs((start_date - base).days) % length)

        # gen dates
        self._dates = []
        while not start_date > end_date:
            self._dates.append(start_date)
            start_date += dt.timedelta(days=length)

    @property
    def data(self):
        return self._data

    # ====================================================================================
    #              ^ fixed   |   v not fixed
    # ====================================================================================

    def recalc(self, data_kind, dv, categories):
        self._data = dict()
        # calculation
        for cat in categories:
            key, issues = self._auto_filter(cat)
            key += f': {cat}'
            self._data.update({key: [_calculator(data_kind, issues, date) for date in self._dates]})
        # diff
        if dv:
            for key, values in self._data.items():
                for i in range(len(values) - 1, 0, -1):  # start:stop:step, use reverse order
                    values[i] -= values[i - 1]
                values[0] = 0
        # additional data
        self._data.update({'__date': self._dates,
                           '__kind': data_kind,
                           '__unit': 'hrs/dt' if dv else 'hrs'})
