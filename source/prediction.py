def linreg(X, Y):
    """
    return a,b in solution to y = ax + b such that root-mean-square distance between trend line
    and original points is minimized
    """
    N = len(X)
    Sx = Sy = Sxx = Syy = Sxy = 0.0
    for x, y in zip(X, Y):
        Sx = Sx + x
        Sy = Sy + y
        Sxx = Sxx + x * x
        Syy = Syy + y * y
        Sxy = Sxy + x * y
    det = Sxx * N - Sx * Sx
    return (Sxy * N - Sy * Sx) / det, (Sxx * Sy - Sx * Sxy) / det


def trends(d, row, start=None):
    """ Calculate linear regression factors of data row.
    row is name of data row
    return tuple (a,b) for y(x)=ax+b
    count x as date index, zero-based"""
    if row not in [key for key in d[next(iter(d))].keys()]:
        raise Exception(f'"{row}" not present in data.')
    if len(d.keys()) < 2:
        raise Exception("Can't calculate trends based single value.")
    # TODO: redefine date range
    dates = [date for date in d.keys() if start is None or not (date < start.date())]
    # calculate data regression
    original = [d[date][row] for date in dates]
    midc = linreg(range(len(original)), original)  # middle linear regression a,b
    midval = [midc[0] * i + midc[1] for i in range(len(original))]  # middle data row
    # calculate high regression
    maxval = [(i, val[1]) for i, val in enumerate(zip(midval, original))
              if val[1] > val[0]]  # get (index, value) for values higher middle
    assert len(maxval) > 1
    maxc = linreg(*list(zip(*maxval)))
    # calculate low regression
    minval = [(i, val[1]) for i, val in enumerate(zip(midval, original))
              if val[1] < val[0]]  # get (index, value) for values lower middle
    assert len(minval) > 1
    minc = linreg(*list(zip(*minval)))
    # return with fixed angles
    return {'name': row,
            'start': dates[0],
            'end': dates[-1],
            'mid': midc,
            'min': (min(midc[0], minc[0]), minc[1]),
            'max': (max(midc[0], maxc[0]), maxc[1])}