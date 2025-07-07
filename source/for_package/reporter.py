import datetime as dt
from data_access import linked_issues, issue_times, get_start_date
from dateutil.rrule import rrule, DAILY
from dateutil.relativedelta import relativedelta
from types import SimpleNamespace

def _iso_split(s, split):
    """ Splitter helper for converting ISO dt notation"""
    if split in s:
        n, s = s.split(split)
    else:
        n = 0
    if n == '':
        n = 0
    return int(n), s


class Expendo:
    def __init__(self, issues: list, **kwargs):
        today = dt.datetime.now(dt.timezone.utc).date()
        self._options = {'sprint_len': 14,
                         'sprint_base': today,
                         'issue_type': ['task', 'bug'],
                         'issue_resolution': ['fixed'],
                         'issue_wip': ['inProgress', 'testing'],
                         'day_len': 8,
                         'week_len': 5,
                         'future': 365}
        self._options.update(kwargs)
        self._issues = list(filter(lambda x: x.type.key in self._options['issue_type'], issues))
        self._update_dates()

    def _update_dates(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        self._start = get_start_date(self._issues)
        shift = abs((today - self._options['sprint_base']).days) % self._options['sprint_len']
        self._active_start = today - dt.timedelta(days=self._options['sprint_len'] - shift)
        self._future_start = today + dt.timedelta(days=shift)
        self._sprint_start = (self._start -
                              dt.timedelta(days=self._options['sprint_len'] -
                                                abs((self._start - self._options['sprint_base']).days) %
                                                self._options['sprint_len']))
        self._sprints = [r.date() for r in rrule(DAILY,
                                                 interval=self._options['sprint_len'],
                                                 dtstart=self._sprint_start,
                                                 until=self._future_start)]
        self._days = [r.date() for r in rrule(DAILY,
                                              dtstart=self._start,
                                              until=today)]
        self._future_date = self._future_start + relativedelta(days=self._options['future'])

    def _iso_hrs(self, s):
        """ Convert ISO dt notation to hours.
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
        return (weeks * self._options['week_len'] + days) * self._options['day_len'] + hours

    @property
    def dates(self):
        """Daily list of issues lifetime's dates"""
        return self._days

    @property
    def sprints(self):
        """List of sprints start dates"""
        return self._sprints

    @property
    def active_sprint(self):
        """Date of active sprint start"""
        return self._active_start

    @property
    def future_sprint(self):
        """Date of future sprint start"""
        return self._future_start

    @property
    def first_date(self):
        """Date of first estimation"""
        return self._start

    def estimate(self, date):
        """
        Summ issues estimate up to the date (including).
        Assumed closed task always has zero estimation.
        :param date: date part value of datetime
        :return: int hours
        """
        return sum([next((self._iso_hrs(s['value']) for s in issue_times(issue)
                          if s['kind'] == 'estimation' and s['date'].date() <= date), 0)
                    for issue in self._issues])

    def spent(self, date, period: int = 0):
        """
        Summ issues spent up to the date (including), total or for a period.
        :param date: date part value of datetime
        :param period: period length in days, zero means all from the beginning
        :return: int hours
        """
        return sum([next((self._iso_hrs(s['value']) for s in issue_times(issue)
                          if s['kind'] == 'spent' and s['date'].date() <= date), 0) -
                    (next((self._iso_hrs(s['value']) for s in issue_times(issue)
                           if s['kind'] == 'spent' and s['date'].date() <= date -
                           dt.timedelta(days=period)), 0) if period else 0)
                    for issue in self._issues])

    def count_created(self, date, period: int = 0):
        """
        Count issues created up to the date (including),
        total or for a period.
        :param date: date part value of datetime
        :param period: period length in days, zero means all from the beginning
        :return: int issues count
        """
        dates = [dt.datetime.strptime(issue.createdAt, '%Y-%m-%dT%H:%M:%S.%f%z').date()
                 for issue in self._issues]
        dates.sort()
        predate = date - dt.timedelta(days=period)
        prev = next((i for i, d in enumerate(dates) if d > predate),
                    len(dates) if dates[-1] <= predate else 0) if period else 0
        return next((i for i, d in enumerate(dates) if d > date), len(dates) if dates[-1] <= date else 0) - prev

    def _issue_original(self, issue):
        """Return start, end and initial estimate value at the issue start moment.
        If unable to detect start or end - return future dates."""
        # start date is date of first InProgress status
        # if start date unknown - return future
        start_date = next((t['date'] for t in reversed(issue_times(issue))
                           if t['kind'] == 'status' and t['value'] in self._options['issue_wip']),
                          self._future_date)
        # final date is date of last Fixed resolution
        # if final date unknown - return future
        final_date = next((t['date'] for t in issue_times(issue)
                           if t['kind'] == 'resolution' and t['value'] in self._options['issue_resolution']),
                          self._future_date)
        # if final_date found, but start_data wasn't (issue closed successfully from backlog)
        # correct start_date to the final_date
        start_date = min(start_date, final_date)
        # find last estimation before start
        # if task not estimated before start - find any first estimation
        est = next((self._iso_hrs(s['value']) for s in issue_times(issue)
                    if s['kind'] == 'estimation' and s['date'].date() <= start_date.date()),
                   next((self._iso_hrs(s['value']) for s in reversed(issue_times(issue))
                         if s['kind'] == 'estimation'), 0))
        r = {'start': start_date.date(),
             'end': final_date.date(),
             'original': est,
             'created': dt.datetime.strptime(issue.createdAt, '%Y-%m-%dT%H:%M:%S.%f%z').date(),
             'valuable': issue.resolution is None or issue.resolution.key in self._options['issue_resolution'],
             'finished': issue.resolution is not None and issue.resolution.key in self._options['issue_resolution']}
        return SimpleNamespace(**r)


def scan(issues, types: list = None) -> str:
    """
    Helper function to scan for subtasks (any deep) of issues. Extract all the issues with required types.
    :param issues: iterable of YT issues objects
    :param types: list of issue types to be selected (default is ['task', 'bug'])
    :return: comma-separated issues keys for next Tracker query.
    """
    if types is None:
        types = ['task', 'bug']
    tickets = {issue.key for issue in issues if issue.type.key in types}
    ancestors = [issue for issue in issues if issue.type.key not in types]
    while ancestors:
        children = linked_issues(ancestors.pop())
        tickets.update({issue.key for issue in children if issue.type.key in types})
        ancestors.extend([issue for issue in children if issue.type.key not in types])
    return ",".join(tickets)
