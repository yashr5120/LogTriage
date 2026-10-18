from logtriage.config import AggregatorConfig, RulesConfig
from logtriage.models import SeverityLevel
from logtriage.processing.filters import SeverityFilter
from logtriage.processing.parser import LogParser
from logtriage.processing.traceback import TracebackAssembler


def test_json_and_case_insensitive_severity() -> None:
    parser = LogParser()
    record = parser.parse_line('{"level":"error","message":"Connection refused"}', 1)
    result = SeverityFilter(RulesConfig()).classify_and_filter(record)
    assert result.normalized_severity == SeverityLevel.HIGH
    assert result.is_error_candidate


def test_traceback_is_assembled() -> None:
    parser = LogParser()
    rules = SeverityFilter(RulesConfig())
    assembler = TracebackAssembler(AggregatorConfig(inactivity_timeout_seconds=999))
    lines = [
        "ERROR Traceback (most recent call last):",
        '  File "app.py", line 4, in main',
        "ValueError: bad input",
        "INFO recovered",
    ]
    completed = []
    for number, line in enumerate(lines, 1):
        completed.extend(assembler.process_record(
            rules.classify_and_filter(parser.parse_line(line, number)), now=float(number)
        ))
    completed.extend(assembler.flush())
    assert completed
    assert completed[0].is_traceback
    assert completed[0].exception_type == "ValueError"
