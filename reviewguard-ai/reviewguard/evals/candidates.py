"""Seed examples for reviewer adjudication; these are not verified ground truth."""

from reviewguard.schemas import AgentType
from reviewguard.evals.models import EvaluationCase


def _case(
    case_id: str,
    agent: AgentType,
    scenario: str,
    source: str,
    anchor: str | None = None,
    severity: str = "MEDIUM",
    existing_tests: dict[str, str] | None = None,
) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        scenario_type=scenario,
        annotation_status="needs_review",
        target_agent=agent,
        filename=f"{case_id}.py",
        source=source,
        existing_tests=existing_tests,
        expected_findings=(
            [{"label": scenario, "anchor": anchor, "severity": severity}]
            if anchor is not None
            else []
        ),
    )


def candidate_cases() -> list[EvaluationCase]:
    """Return 30 labeled candidates (10 per reviewer) that still require review."""
    quality = AgentType.code_quality
    security = AgentType.security
    coverage = AgentType.test_coverage
    cases = [
        _case("cq-01", quality, "off_by_one", "def total(values):\n    result = 0\n    for index in range(1, len(values)):\n        result += values[index]\n    return result\n", "for index in range(1, len(values)):", "HIGH"),
        _case("cq-02", quality, "negative_values", "def largest(values):\n    result = 0\n    for value in values:\n        if value > result:\n            result = value\n    return result\n", "result = 0", "MEDIUM"),
        _case("cq-03", quality, "empty_input", "def mean(values):\n    return sum(values) / len(values)\n", "return sum(values) / len(values)", "MEDIUM"),
        _case("cq-04", quality, "mutation_during_iteration", "def remove_negatives(values):\n    for value in values:\n        if value < 0:\n            values.remove(value)\n    return values\n", "values.remove(value)", "MEDIUM"),
        _case("cq-05", quality, "incorrect_boundary", "def is_adult(age):\n    return age > 18\n", "return age > 18", "MEDIUM"),
        _case("cq-06", quality, "valid_accumulator", "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"),
        _case("cq-07", quality, "valid_negative_maximum", "def largest(values):\n    if not values:\n        return None\n    result = values[0]\n    for value in values[1:]:\n        if value > result:\n            result = value\n    return result\n"),
        _case("cq-08", quality, "explicit_empty_guard", "def mean(values):\n    if not values:\n        raise ValueError('values cannot be empty')\n    return sum(values) / len(values)\n"),
        _case("cq-09", quality, "safe_filter", "def remove_negatives(values):\n    return [value for value in values if value >= 0]\n"),
        _case("cq-10", quality, "explicit_boundary", "def is_adult(age):\n    return age >= 18\n"),
        _case("sec-01", security, "sql_injection", "def find_user(cursor, user_id):\n    query = 'SELECT * FROM users WHERE id = ' + user_id\n    cursor.execute(query)\n", "cursor.execute(query)", "HIGH"),
        _case("sec-02", security, "shell_injection", "import subprocess\n\ndef ping(host):\n    subprocess.run('ping ' + host, shell=True)\n", "subprocess.run('ping ' + host, shell=True)", "HIGH"),
        _case("sec-03", security, "unsafe_deserialization", "import pickle\n\ndef load_record(data):\n    return pickle.loads(data)\n", "pickle.loads(data)", "HIGH"),
        _case("sec-04", security, "dynamic_code_execution", "def calculate(expression):\n    return eval(expression)\n", "return eval(expression)", "HIGH"),
        _case("sec-05", security, "unsafe_archive_path", "from pathlib import Path\n\ndef output_path(root, member):\n    return Path(root) / member\n", "return Path(root) / member", "MEDIUM"),
        _case("sec-06", security, "parameterized_sql", "def find_user(cursor, user_id):\n    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))\n"),
        _case("sec-07", security, "safe_subprocess_arguments", "import subprocess\n\ndef ping(host):\n    subprocess.run(['ping', host], shell=False, check=True)\n"),
        _case("sec-08", security, "safe_literal_parser", "import ast\n\ndef parse_value(text):\n    return ast.literal_eval(text)\n"),
        _case("sec-09", security, "environment_secret", "import os\n\ndef token():\n    return os.environ['SERVICE_TOKEN']\n"),
        _case("sec-10", security, "fixed_path", "from pathlib import Path\n\ndef read_config(root):\n    return (Path(root) / 'settings.json').read_text(encoding='utf-8')\n"),
        _case("tc-01", coverage, "numeric_boundary_tests", "def clamp(value, lower, upper):\n    return max(lower, min(value, upper))\n", "return max(lower, min(value, upper))", "LOW"),
        _case("tc-02", coverage, "invalid_input_tests", "def parse_port(value):\n    port = int(value)\n    if not 1 <= port <= 65535:\n        raise ValueError('invalid port')\n    return port\n", "if not 1 <= port <= 65535:", "LOW"),
        _case("tc-03", coverage, "empty_collection_tests", "def first_item(items):\n    return items[0]\n", "return items[0]", "MEDIUM"),
        _case("tc-04", coverage, "exception_path_tests", "def load_text(path):\n    with open(path, encoding='utf-8') as stream:\n        return stream.read()\n", "with open(path, encoding='utf-8') as stream:", "LOW"),
        _case("tc-05", coverage, "rounding_boundary_tests", "def apply_discount(price, percent):\n    if not 0 <= percent <= 100:\n        raise ValueError('invalid percent')\n    return round(price * (1 - percent / 100), 2)\n", "if not 0 <= percent <= 100:", "LOW"),
        _case("tc-06", coverage, "covered_clamp_behavior", "def clamp(value, lower, upper):\n    return max(lower, min(value, upper))\n", existing_tests={"test_clamp.py": "def test_inside_range():\n    assert clamp(5, 0, 10) == 5\n\ndef test_lower_and_upper_bounds():\n    assert clamp(-1, 0, 10) == 0\n    assert clamp(11, 0, 10) == 10\n"}),
        _case("tc-07", coverage, "covered_port_validation", "def parse_port(value):\n    port = int(value)\n    if not 1 <= port <= 65535:\n        raise ValueError('invalid port')\n    return port\n", existing_tests={"test_port.py": "import pytest\n@pytest.mark.parametrize('value', ['1', '65535'])\ndef test_valid(value):\n    assert 1 <= parse_port(value) <= 65535\n@pytest.mark.parametrize('value', ['0', '65536', 'bad'])\ndef test_invalid(value):\n    with pytest.raises((ValueError, TypeError)):\n        parse_port(value)\n"}),
        _case("tc-08", coverage, "covered_empty_collection", "def first_item(items):\n    return items[0]\n", existing_tests={"test_first.py": "import pytest\ndef test_first_item():\n    assert first_item(['a']) == 'a'\ndef test_empty_items_raises():\n    with pytest.raises(IndexError):\n        first_item([])\n"}),
        _case("tc-09", coverage, "covered_file_errors", "def load_text(path):\n    with open(path, encoding='utf-8') as stream:\n        return stream.read()\n", existing_tests={"test_load.py": "def test_reads_file(tmp_path):\n    path = tmp_path / 'x.txt'\n    path.write_text('ok', encoding='utf-8')\n    assert load_text(path) == 'ok'\ndef test_missing_file_raises(tmp_path):\n    with pytest.raises(FileNotFoundError):\n        load_text(tmp_path / 'missing')\n"}),
        _case("tc-10", coverage, "covered_discount_boundaries", "def apply_discount(price, percent):\n    if not 0 <= percent <= 100:\n        raise ValueError('invalid percent')\n    return round(price * (1 - percent / 100), 2)\n", existing_tests={"test_discount.py": "import pytest\n@pytest.mark.parametrize(('price', 'percent', 'expected'), [(10, 0, 10), (10, 100, 0), (10, 25, 7.5)])\ndef test_discount(price, percent, expected):\n    assert apply_discount(price, percent) == expected\n@pytest.mark.parametrize('percent', [-1, 101])\ndef test_invalid_percent(percent):\n    with pytest.raises(ValueError):\n        apply_discount(10, percent)\n"}),
    ]
    return cases
