import joshua.joshua_agent as joshua_agent
import doctest


def test_doctest():
    failure_count = doctest.testmod(joshua_agent)[0]
    assert failure_count == 0
