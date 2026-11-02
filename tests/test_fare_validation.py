from types import SimpleNamespace
from worker_v2 import valid_fare


def fare(**kw):
    data=dict(airline="KE",depart_date="2027-03-12",currency="TWD",price_total=6366,trip_type="單程",return_flight_no="",return_depart_date="")
    data.update(kw)
    return SimpleNamespace(**data)


def test_valid_oneway():
    assert valid_fare(fare(), airline="KE", depart="2027-03-12", ret="")


def test_wrong_date_airline_currency_or_missing_total_rejected():
    for f in (fare(depart_date="2027-03-11"),fare(airline="CI"),fare(currency="USD"),fare(price_total=None),fare(price_total=0)):
        assert not valid_fare(f,airline="KE",depart="2027-03-12",ret="")


def test_round_trip_requires_matching_return_flight():
    assert not valid_fare(fare(),airline="KE",depart="2027-03-12",ret="2027-03-19")
    assert valid_fare(fare(trip_type="來回",return_flight_no="KE123",return_depart_date="2027-03-19"),airline="KE",depart="2027-03-12",ret="2027-03-19")
    assert not valid_fare(fare(trip_type="來回",return_flight_no="KE123",return_depart_date="2027-03-20"),airline="KE",depart="2027-03-12",ret="2027-03-19")
