"""A fixed "today" for the bench: date.today() and datetime.now() return the day of the delivery being
measured (the time of day stays real). Imported before anything of Physarum, so its modules see it."""
import datetime as _dt

_real_date, _real_dt = _dt.date, _dt.datetime
_day = [_real_date.today()]


def set_today(d) -> None:
    _day[0] = _real_date.fromisoformat(str(d)) if not isinstance(d, _real_date) else d


class FakeDate(_real_date):
    @classmethod
    def today(cls):
        d = _day[0]
        return cls(d.year, d.month, d.day)


class FakeDateTime(_real_dt):
    @classmethod
    def now(cls, tz=None):
        r, d = _real_dt.now(tz), _day[0]
        return cls(d.year, d.month, d.day, r.hour, r.minute, r.second, r.microsecond, tzinfo=r.tzinfo)

    @classmethod
    def today(cls):
        return cls.now()


_dt.date = FakeDate
_dt.datetime = FakeDateTime
