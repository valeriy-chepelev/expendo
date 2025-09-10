"""
Data Engine module for expendo2 project
(c) VCh 2025
"""

from functools import lru_cache
import datetime as dt
from dateutil.relativedelta import relativedelta
import logging
from types import SimpleNamespace
from prettytable import PrettyTable
from segmentation import calculate_lambda, bottom_up_segmentation
from natsort import natsorted
from colorama import Fore, Back, Style

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


@lru_cache(maxsize=None)
def _project(issue):
    """ Return one issue main project name"""
    return p.display if (p := issue.project) is not None else 'NoProject'


"""
@lru_cache(maxsize=None)
def _parent(issue):
    # TODO: caching now works here!!!
    return issue.parent


@lru_cache(maxsize=None)
def _epic(issue):
    x = issue
    while (p := _parent(x)) is not None:
        x = p
    return (x.key, x.summary) if x.type.key == 'epic' else ('0', 'NoEpic')
"""


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

POSITIVE = 1.0
NEGATIVE = -1.0


def slope(kind: str) -> float:
    match kind.lower():
        case 'spent' | 'burn':
            s = POSITIVE
        case 'estimate' | 'original':
            s = NEGATIVE
        case _:
            s = 0.0
    return s


def _cache_info():
    logging.debug(f'Cache stat _times {issue_times.cache_info()}')
    logging.debug(f'Cache stat _original {issue_original.cache_info()}')
    logging.debug(f'Cache stat _tags {_tags.cache_info()}')
    logging.debug(f'Cache stat _queues {_queue.cache_info()}')
    logging.debug(f'Cache stat _components {_components.cache_info()}')
    logging.debug(f'Cache stat _project {_project.cache_info()}')


class DataManager:
    def __init__(self, issues, tree):
        super(DataManager, self).__init__()
        # static data
        self.issues = issues  # issues list
        self.tree = tree  # issues epics info
        self._stat = ''  # statistical data string
        self._start_date = TODAY
        # categories
        self.tags = []
        self.queues = []
        self.components = []
        self.projects = dict()
        self.epics = dict()
        # dynamic data
        self._dates = []
        self._data = dict()
        self._segments = []
        # updates
        print('Calculating statistics...')
        self._update_stat()
        print('Updating categories...')
        self._update_categories()
        _cache_info()
        print('Calculating total start date...')
        self._start_date = get_start_date(self.issues).date()

    def _epic(self, issue):
        """Epics is dict of tuples. Return Tuple(Epic key, Epic summary)"""
        return self.tree[issue.key]

    def _match(self, category):
        """Function fabric - return issue match function"""

        def issue_type(issue, val):
            return issue.type.key == val

        def tag(issue, val):
            return val in _tags(issue)

        def component(issue, val):
            return val in _components(issue)

        def queue(issue, val):
            return val == _queue(issue)

        def project(issue, val):
            # DONE: BUG! val is now a project index in self.projects dict, but _project return name
            return self.projects[val] == _project(issue)

        def epic(issue, val):
            return val == self._epic(issue)[1]  # Match by summary

        assert category in locals()
        f = locals()[category]
        assert callable(f)
        return f

    def _select_add(self, category, value, issues=None):
        matcher = self._match(category)
        result = {t for t in self.issues if matcher(t, value)}
        if issues is not None:
            result.update(issues)
        return list(result)

    def _select_sub(self, issues, category, value):
        matcher = self._match(category)
        return [t for t in issues if not matcher(t, value)]

    def _category(self, value):
        if value in self.tags:
            return 'tag'
        if value in self.components:
            return 'component'
        if value in self.queues:
            return 'queue'
        if value in self.projects:
            return 'project'
        if value in self.epics:
            return 'epic'
        return ''

    def _auto_filter(self, include_value, exclude_values):
        """ Filter issues matched category value.
        Category determined automatically by the value.
        :param include_value: category value
        :return: tuple (Category name, list of issues)
        """
        # TODO: make join of filtered issues (OR - for case when value match some classes)
        issues = self._select_add(name := self._category(include_value), include_value)
        if name == 'project':
            name = self.projects[include_value]
        if name == 'epic':
            name = self.epics[include_value]
        for val in exclude_values:
            issues = self._select_sub(issues, self._category(val), val)
        return name, issues

    def _update_categories(self):
        # collect categories info, called ones from constructor
        t = set()
        q = set()
        c = set()
        p = set()
        e = dict()
        for issue in self.issues:
            t.update(_tags(issue))
            q.add(_queue(issue))
            c.update(_components(issue))
            p.add(_project(issue))
            epic = self._epic(issue)
            try:
                key = epic[0][str(epic[0]).index('-') + 1:]
            except ValueError:
                key = epic[0]
            e.update({key: epic[1]})
        self.tags = natsorted(list(t))
        self.queues = natsorted(list(q))
        self.components = natsorted(list(c))
        p = sorted(p)
        try:
            p.pop(p.index('NoProject'))
            p.insert(0, 'NoProject')
        except ValueError:
            pass
        self.projects = {f"P{idx}": name
                         for idx, name in enumerate(p, start=0)}
        self.epics = dict(natsorted(e.items(), key=lambda x: x[0]))

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
        tbl.add_row(row('Tasks', self._select_add('issue_type', 'task')))
        tbl.add_row(row('Bugs', self._select_add('issue_type', 'bug')))
        tbl.add_row(row('Total', self.issues))
        tbl.align = 'r'
        self._stat = tbl.get_string()

    @property
    def categories(self):
        return list(set(self.tags) | set(self.queues) | set(self.components) |
                    self.projects.keys() | self.epics.keys())

    @property
    def categories_info(self):
        divider = Style.RESET_ALL + ', ' + Fore.GREEN
        info = [f'- Queues: {Fore.GREEN}{divider.join(self.queues)}{Style.RESET_ALL}'
                if len(self.queues) > 1 else None,
                f'- Tags: {Fore.GREEN}{divider.join(self.tags)}{Style.RESET_ALL}'
                if len(self.tags) else None,
                f'- Components: {Fore.GREEN}{divider.join(self.components)}{Style.RESET_ALL}'
                if len(self.components) else None]
        if len(self.projects) > 1:
            p_list = [f'{Fore.GREEN}{key}{Style.RESET_ALL}: {val}' for key, val in self.projects.items()]
            info.append(f'- Projects: {", ".join(p_list)}')
        if len(self.epics) > 1:
            e_list = [f'{Fore.GREEN}{key}{Style.RESET_ALL}: {val}' for key, val in self.epics.items()]
            info.append(f'- Root epics: {", ".join(e_list)}{Style.RESET_ALL}')
        info = [s for s in info if s is not None]
        return '\n'.join(info) if len(info) else '- Not found.'

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
        logging.debug(f'End date {end_date.strftime("%d.%m.%y")}')
        end_date -= dt.timedelta(days=abs((end_date - base).days) % length)
        logging.debug(f'Aligned end date {end_date.strftime("%d.%m.%y")}')

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
        logging.debug(f'Start date {start_date.strftime("%d.%m.%y")}')
        start_date -= dt.timedelta(days=length - abs((start_date - base).days) % length)
        logging.debug(f'Aligned start date {start_date.strftime("%d.%m.%y")}')

        # gen dates
        self._dates = []
        while not start_date > end_date:
            self._dates.append(start_date)
            start_date += dt.timedelta(days=length)

    @property
    def data(self):
        return self._data

    def recalc(self, data_kind, dv, categories, exclusions):
        self._data = dict()
        # calculation
        for cat in categories:
            key, issues = self._auto_filter(cat, exclusions)
            key += f': {cat}'
            self._data.update({key: [_calculator(data_kind, issues, date) for date in self._dates]})
        # total
        if len(categories) == 0:
            self._data.update({'TOTAL': [_calculator(data_kind, self.issues, date) for date in self._dates]})
        # diff
        if dv:
            for key, values in self._data.items():
                for i in range(len(values) - 1, 0, -1):  # start:stop:step, use reverse order
                    values[i] -= values[i - 1]
                values[0] = values[1] if len(values) > 1 else 0
        # additional data
        self._data.update({'__date': self._dates,
                           '__kind': data_kind,
                           '__unit': 'hrs/dt' if dv else 'hrs',
                           '__dv': dv})
        self._segments = []

    @property
    def segments(self):
        return self._segments

    def update_segments(self, method, c):
        self._segments = []
        for data_name in [t for t in self._data.keys() if t[:2] != '__']:
            lam = calculate_lambda(self._data[data_name], c, method)
            # show only segments with 'slope' or all for dv
            self._segments.append([s for s in bottom_up_segmentation(self._data[data_name],
                                                                     2 + (len(self._data[data_name]) // 10), lam)
                                   if (s['a'] * slope(self._data['__kind']) > 0) or self._data['__dv']])
