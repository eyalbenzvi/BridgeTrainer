"""LIN harvesting: parser, contract derivation, divergence extraction."""
from bridge_trainer.harvest.lin import (auction_to_contract, find_divergences,
                                        parse_lin)

LIN = (
    "vg|TEST EVENT,SEG1,I,1,2,TEAMA,0,TEAMB,0|\n"
    "rs|3HN-2,3HN=,4SE=,4SE+1|\n"
    "pn|a,b,c,d,e,f,g,h|pg||\n"
    "qx|o1|st||md|3SAT2H9765DT987CQJ,SK863HTDKJ42CT864,"
    "SJ74HAQJ82DQ63CA9,|sv|o|"
    "mb|1H|mb|p|mb|3H|mb|p|mb|p|mb|p|pg||\n"
    "qx|c1|st||md|3SAT2H9765DT987CQJ,SK863HTDKJ42CT864,"
    "SJ74HAQJ82DQ63CA9,|sv|o|"
    "mb|1H|mb|p|mb|2H!|mb|p|mb|p|mb|p|pg||\n"
)


def test_parse_lin_basics():
    boards = parse_lin(LIN)
    assert len(boards) == 2
    o1 = boards[0]
    assert (o1.room, o1.number, o1.dealer, o1.vul) == ("o", 1, "N", "None")
    assert o1.auction == ["1H", "P", "3H", "P", "P", "P"]
    assert o1.result == "3HN-2"
    # 4th hand derived from the other three.
    assert len(o1.hands["E"].replace(".", "")) == 13
    assert o1.hands["S"] == "AT2.9765.T987.QJ"
    assert o1.teams == "TEAMA v TEAMB"


def test_alert_suffix_and_calls_normalized():
    boards = parse_lin(LIN)
    c1 = boards[1]
    assert c1.auction == ["1H", "P", "2H", "P", "P", "P"]


def test_auction_to_contract_first_namer_and_double():
    fc = auction_to_contract("N", ["1H", "P", "3H", "P", "P", "P"])
    assert (fc.level, fc.denom, fc.declarer, fc.doubled) == (3, "H", "N", False)
    fc2 = auction_to_contract("W", ["1NT", "P", "P", "X", "P", "P", "P"])
    assert (fc2.level, fc2.denom, fc2.declarer, fc2.doubled) == (1, "NT", "W", True)
    fc3 = auction_to_contract("N", ["P", "P", "P", "P"])
    assert fc3.passed_out


def test_divergence_extraction():
    divs = find_divergences(parse_lin(LIN))
    assert len(divs) == 1
    d = divs[0]
    assert d.number == 1
    assert d.stem == ["1H", "P"]
    assert d.hero == "S"
    assert d.calls == {"o": "3H", "c": "2H"}
    assert str(d.contracts["o"]) == "3HN"
    assert str(d.contracts["c"]) == "2HN"
    assert d.results == {"o": "3HN-2", "c": "3HN="}
